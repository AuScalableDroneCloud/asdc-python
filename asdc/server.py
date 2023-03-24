"""
Server extensions for jupyterhub
Experimental server flow additions
- Authorization Code Flow with Proof Key for Code Exchange (PKCE)
"""
import tornado.ioloop
import tornado.web
import tornado.httpclient
import tornado.httputil
import sys
import os
import re
from slugify import slugify
import datetime
import json
import requests

#Debug logging
from tornado.log import enable_pretty_logging
enable_pretty_logging()
import logging
logger = logging.getLogger("asdc-server")

from pathlib import Path
from . import utils
import subprocess

#prefix = os.getenv('JUPYTERHUB_SERVICE_PREFIX')
#user = os.getenv('JUPYTERHUB_USER')
baseurl = os.getenv('JUPYTERHUB_URL')
server = os.getenv('JUPYTERHUB_SERVER_NAME', '')
user = os.getenv('JUPYTERHUB_USER', '')
#fullurl = f'{baseurl}/{prefix}'
fullurl = f'/user-redirect/'
if len(user):
    redirected = f'/user/{user}/'
else:
    redirected = fullurl
#Add named server
if len(server):
    fullurl = f'{fullurl}{server}/'
    redirected = f'{redirected}{server}/'

root_doc = """
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="utf-8" />
    <title>ASDC Jupyterhub Interface</title>
</head>

<body>
    <h1>ASDC Jupyterhub Interface</h3>
    <p>This extension provides an OAuth2 callback for Jupyter environments</p>
    <p>(plus ASDC API extensions)</p>
    <p>{EXTRA}</p>
</body>

</html>
"""

class RootHandler(tornado.web.RequestHandler):
    def get(self):
        tokens = self.application.tokens
        if tokens:
            #Show ID token data
            import jwt
            id_jwt = tokens.get("id_token")
            decoded = jwt.decode(id_jwt, options={"verify_signature": False}) # works in PyJWT >= v2.0
            self.write(root_doc.format(EXTRA="You are authenticated with the API: " + str(decoded['payload'])))
        else:
            self.write(root_doc.format(EXTRA=f"(you are not authenticated with the API)<br><a href='{redirected}/asdc/redirect?path=nowhere'>Authenticate</a>"))


py_base = """# + [markdown] inputHidden=false outputHidden=false
# # Loading a data set from ASDC WebODM
#
# This notebook / script will load a specific task dataset
#

# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os

asdc.set_selection({PID}, '{TID}')
task_name = '{TNAME}'
filename = '{ASSET}'
#Create a working dir for the task
pathlib.Path(task_name).mkdir(parents=True, exist_ok=True)
os.chdir(task_name)
asdc.download_asset(filename)

# + inputHidden=false outputHidden=false
"""

handler_tif = """
from IPython.display import display
from PIL import Image

im = Image.open(filename)
im.thumbnail((350,350),Image.LANCZOS)
display(im)
"""

handler_laz = """
#TODO: plot .laz file
"""

handler_zip = """
#TODO: unzip and plot 3d model .zip
"""

handler_glb = """
#TODO: plot 3d model .glb
"""


import_doc = """
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="utf-8" />
    <title>ASDC API server</title>
</head>

<script>
{script}
</script>

<body>
    <h1>ASDC API Request</h3>
    <p>Request processed for {FN}
    <a href="{redirected}lab/tree/{FN}">(Output here)</a>
    </p>
</body>

</html>
"""

nowhere_doc = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>Auth completed, closing</title>
</head>

<body onload="window.close();">
    <h3>OAuth2 Callback succeeded, you can close this window</h3>
    <a href="javascript:window.close()">click to close</a>

    <script type="text/javascript">
        //Close the window
        window.close();
    </script>
</body>

</html>
"""

################################################################################################################
#Using PKCE to avoid storing client secret
#https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-proof-key-for-code-exchange-pkce
provider_url = os.getenv('JUPYTER_OAUTH2_AUTH_PROVIDER_URL', '')
client_id =  os.getenv('JUPYTER_OAUTH2_API_CLIENT_ID', '') #Must use the API client id, not the regular webapp id
scope = 'openid profile email offline_access' #offline_access scope added for refresh token
audience = os.getenv('JUPYTER_OAUTH2_API_AUDIENCE', 'https://asdc.cloud.edu.au/api')
state = audience + server + str(int(datetime.datetime.utcnow().timestamp())) # seconds have been converted to integers
callback_uri = f'{baseurl}{fullurl}asdc/callback'

# using requests implementation
from authlib.integrations.requests_client import OAuth2Session
#https://community.auth0.com/t/surface-custom-scopes-on-consent-screen-for-first-party-applications/86291
class OAuth2SessionProxy(OAuth2Session):
    """
    need to extend OAuth2Session in order to include the `audience`
    param in the OAuth2Session.EXTRA_AUTHORIZE_PARAMS tuple, it's used
    by Auth0 in determining which API this request is associated with
    """
    def __init__(self, *args, **kwargs):
        super(OAuth2SessionProxy, self).__init__(*args, **kwargs)

    EXTRA_AUTHORIZE_PARAMS = (
        'response_mode',
        'nonce',
        'prompt',
        'login_hint',
        'audience',
        'code_challenge',
        'code_challenge_method',
    )

from authlib.common.security import generate_token
# remember to save this nonce for verification
#nonce = generate_token()
code_verifier = generate_token(48)
from authlib.oauth2.rfc7636 import create_s256_code_challenge
code_challenge = create_s256_code_challenge(code_verifier)
#client.create_authorization_url(url, redirect_uri='xxx', nonce=nonce, ...)
client = OAuth2SessionProxy(client_id, scope=scope, redirect_uri=callback_uri, audience=audience) #, code_challenge_method='S256') #, nonce=nonce, state=env.get("APP_SECRET_KEY"))

authorization_endpoint = f'{provider_url}/authorize'
#uri, state = client.create_authorization_url(authorization_endpoint, nonce=nonce)
#uri, state = client.create_authorization_url(authorization_endpoint, code_verifier=code_verifier)
auth_uri, state = client.create_authorization_url(authorization_endpoint, code_challenge=code_challenge, code_challenge_method='S256', state=state)
#(Use state to verify later)
################################################################################################################

class RequirementsHandler(tornado.web.RequestHandler):
    def get(self):
        #Install requirements.txt for a pipeline
        path = self.get_argument('path')
        redirect = self.get_argument('next', '/lab/tree/')

        if os.path.exists(Path.home() / path / "requirements.txt"):
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=str(Path.home() / path))

        return self.redirect(redirect)

class RedirectHandler(tornado.web.RequestHandler):
    """
    Write the updated projects/tasks and redirect to provided notebook

    Can we get access_token here with an additional redirect?
    - user goes to JHUB_URL/asdc/redirect&path=PATH
    - store PATH on the server so we can redirect to it later
    - user is redirected to the Auth0 login url, with redirect back to /callback
    - if PATH set in /callback, then redirect there after storing the access_token
    """
    def get(self):
        logger.info("Handling redirect")
        projects = [int(p) for p in list(filter(None, re.split('\W+', self.get_argument('projects', ''))))]
        tasks = list(filter(None, re.split('[, ]+', self.get_argument('tasks', ''))))
        redirect = self.get_argument('path', '')
        #Save the redirect path and begin the auth flow
        if redirect == 'nowhere':
            self.application.redirect_path = ""
        else:
            self.application.redirect_path = f"{redirected}lab/tree/{redirect}"
        print(projects,tasks,redirect)

        #utils.write_inputs(projects=projects, tasks=tasks, port=sys.argv[1])
        utils.write_inputs(projects=projects, tasks=tasks)

        #return self.redirect(f"{fullurl}lab/tree/{redirect}")
        return self.redirect(auth_uri)

class ImportHandler(tornado.web.RequestHandler):
    def get(self):
        #Write a python module to import the selected task
        if not 'access_token' in self.application.tokens:
            #Redirect to authorise, then return here
            redirect = self.request.uri.rsplit('/', 1)[-1]
            self.application.redirect_path = f"{redirected}asdc/{redirect}"
            #Remove the redirects= counter
            self.application.redirect_path = re.sub(r'&redirects=\d', '', self.application.redirect_path)
            logger.info(f"No tokens, redirecting, orig url: {self.request.uri} : return: {self.application.redirect_path}")
            return self.redirect(auth_uri)

        logger.info("Handling import")
        project = self.get_argument('project')
        task = self.get_argument('task')
        taskname = slugify(self.get_argument('name'))
        asset = self.get_argument('asset', 'orthophoto.tif')
        redirect = self.get_argument('redirect', 'yes')
        filename = f'{taskname}.py'

        # Write the python script / notebook
        with open(str(Path.home() / filename), 'w') as f:
            nb_doc = py_base
            #Add handler based on asset file extension
            ext = Path(asset).suffix
            if ext == '.tif':
                nb_doc += handler_tif
            elif ext == '.laz':
                nb_doc += handler_laz
            elif ext == '.zip':
                nb_doc += handler_zip
            elif ext == '.glb':
                nb_doc += handler_glb

            f.write(nb_doc.format(PID=project, TID=task, TNAME=taskname, ASSET=asset))

        utils.write_inputs(projects=[project], tasks=[task])

        script = ""
        if redirect == 'yes':
            #script = f'window.location.href="{fullurl}lab/tree/{filename}"'
            return self.redirect(f"{redirected}lab/tree/{filename}")
        else:
            #self.write(import_doc.format(FN=filename, script=script))
            return self.write(import_doc.format(FN=filename, script=""))

class TokensHandler(tornado.web.RequestHandler):
    def get(self):
        logger.info("Handling tokens")
        tokens = self.application.tokens
        if not tokens:
            logger.error(f"Tokens are not available")
            raise tornado.web.HTTPError(
                status_code=404,
                reason="Tokens are not available."
            )

        #Return the token data
        import jwt
        id_jwt = tokens.get("id_token")
        decoded = jwt.decode(id_jwt, options={"verify_signature": False}) # works in PyJWT >= v2.0
        id_token = decoded

        #Check if it is expired, renew expired token
        dt = datetime.datetime.fromtimestamp(tokens['expires_at'])
        now = datetime.datetime.now(tz=None)
        if dt <= now:
            logger.info("Token expired")
            #Use refresh_token to get new token if necessary
            token_endpoint = f'{provider_url}/oauth/token'
            rtoken = tokens["refresh_token"]
            try:
                #Need to create new client
                client = OAuth2SessionProxy(client_id, scope=scope, redirect_uri=callback_uri, audience=audience)
                new_tokens = client.refresh_token(token_endpoint, refresh_token=rtoken)
                logger.info(f"New tokens recieved")
                tokens = new_tokens
            except (Exception) as e:
                #Just return the original tokens
                logger.error(f"Something went wrong: {e}")
                pass

        self.write(tokens)

class CallbackHandler(tornado.web.RequestHandler):
    def get(self):
        #NEW HANDLER - Authorization Code Flow with PKCE
        authorization_response = self.request.uri
        logger.info("/callback")
        token_endpoint = f'{provider_url}/oauth/token'
        #This gets the token using auth code flow
        #THIS SOMETIMES ERRORS WITH http.client.RemoteDisconnected: Remote end closed connection without response
        #https://github.com/requests/requests-oauthlib/blob/master/requests_oauthlib/oauth2_session.py#L191
        retries = 5
        for i in range(retries):
            try:
                client = OAuth2SessionProxy(client_id, scope=scope, redirect_uri=callback_uri, audience=audience)
                tokens = client.fetch_token(token_endpoint, authorization_response=authorization_response, code_verifier=code_verifier, state=state)
                break
            except (requests.exceptions.ConnectionError) as e:
                logger.info(f"Exception in client.fetch_token: {e} retry # {i}")
                pass
        self.application.tokens = tokens #Store on application

        #Re-write the input data, now include the server port to access tokens with
        utils.write_port(sys.argv[1])

        if len(self.application.redirect_path) == 0:
            logger.info(f"Redirect set to nowhere")
            self.write(nowhere_doc)
        else:
            logger.info(f"Redirecting: {self.application.redirect_path}")
            return self.redirect(self.application.redirect_path)

class ServerApplication(tornado.web.Application):

    def __init__(self):
        self.redirect_path = "/";
        self.tokens = {};

        handlers = [
            (r"/", RootHandler),
            (r"/redirect", RedirectHandler),
            (r"/import", ImportHandler),
            (r"/tokens", TokensHandler),
            (r"/callback", CallbackHandler)
        ]
        settings = dict() #your application settings here
        super().__init__(handlers, **settings)

if __name__ == "__main__":
    print("Starting OAuth2 callback server", sys.argv)
    app = ServerApplication()
    app.listen(sys.argv[1])
    tornado.ioloop.IOLoop.current().start()

