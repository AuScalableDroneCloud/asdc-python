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

#Debug logging
from tornado.log import enable_pretty_logging
enable_pretty_logging()
import logging
logger = logging.getLogger("asdc-server")

from pathlib import Path
from . import utils
import subprocess

root_doc = """
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="utf-8" />
    <title>Jupyter_OAuth2</title>
</head>

<body>
    <h1>Jupyter_OAuth2</h3>
    <p>This extension provides an OAuth2 callback for Jupyter environments</p>
    <p>(plus ASDC API extensions)/p>
</body>

</html>
"""

class RootHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(root_doc)


py_base = """# + [markdown] inputHidden=false outputHidden=false
# # Loading a data set from ASDC WebODM
#
# This notebook / script will load a specific task dataset
#

# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os

await asdc.auth.connect()

project_id = '{PID}'
task_id = '{TID}'
task_name = '{TNAME}'
filename = '{ASSET}'
#Create a working dir for the task
pathlib.Path(task_name).mkdir(parents=True, exist_ok=True)
os.chdir(task_name)
asdc.download_asset(project_id, task_id, filename)

asdc.download_asset(filename, project=project_id, task=task_id)

# + inputHidden=false outputHidden=false
if "orthophoto" in filename:
    from IPython.display import display
    from PIL import Image

    im = Image.open(filename)
    im.thumbnail((350,350),Image.ANTIALIAS)
    display(im)
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
    <a href="{fullurl}lab/tree/{FN}">(Output here)</a>
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

#prefix = os.getenv('JUPYTERHUB_SERVICE_PREFIX')
#user = os.getenv('JUPYTERHUB_USER')
baseurl = os.getenv('JUPYTERHUB_URL')
server = os.getenv('JUPYTERHUB_SERVER_NAME', '')
#fullurl = f'{baseurl}/{prefix}'
fullurl = f'/user-redirect/'
if len(server):
    fullurl = f'/user-redirect/{server}/'

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
nonce = generate_token()
code_verifier = generate_token(48)
print("VERIFIER:",code_verifier)
from authlib.oauth2.rfc7636 import create_s256_code_challenge
code_challenge = create_s256_code_challenge(code_verifier)
#client.create_authorization_url(url, redirect_uri='xxx', nonce=nonce, ...)
client = OAuth2SessionProxy(client_id, scope=scope, redirect_uri=callback_uri, audience=audience) #, code_challenge_method='S256') #, nonce=nonce, state=env.get("APP_SECRET_KEY"))

authorization_endpoint = f'{provider_url}/authorize'
#uri, state = client.create_authorization_url(authorization_endpoint, nonce=nonce)
#uri, state = client.create_authorization_url(authorization_endpoint, code_verifier=code_verifier)
auth_uri, state = client.create_authorization_url(authorization_endpoint, code_challenge=code_challenge, code_challenge_method='S256', state=state)
#(Use state to verify later)
print(auth_uri)
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
            self.application.redirect_path = f"{fullurl}lab/tree/{redirect}"
        print(projects,tasks,redirect)

        #utils.write_inputs(projects=projects, tasks=tasks, port=sys.argv[1])
        utils.write_inputs(projects=projects, tasks=tasks)

        #return self.redirect(f"{fullurl}lab/tree/{redirect}")
        return self.redirect(auth_uri)

class ImportHandler(tornado.web.RequestHandler):
    def get(self):
        #Write a python module to import the selected task
        logger.info("Handling import")
        project = self.get_argument('project')
        task = self.get_argument('task')
        taskname = slugify(self.get_argument('name'))
        asset = self.get_argument('asset', 'orthophoto.tif')
        redirect = self.get_argument('redirect', 'yes')
        filename = f'{taskname}.py'

        # Write the python script / notebook
        with open(str(Path.home() / filename), 'w') as f:
            f.write(py_base.format(PID=project, TID=task, TNAME=taskname, ASSET=asset))

        utils.write_inputs(projects=[project], tasks=[task])

        script = ""
        if redirect == 'yes':
            #script = f'window.location.href="{fullurl}lab/tree/{filename}"'
            return self.redirect(f"{fullurl}lab/tree/{filename}")
        else:
            #self.write(import_doc.format(FN=filename, script=script))
            return self.write(import_doc.format(FN=filename, script=""))

class BrowseHandler(tornado.web.RequestHandler):
    def get(self):
        logger.info("Handling filebrowser")
        #Redirects to the mounted project and task folder
        PID = self.get_argument('project')
        TID = self.get_argument('task')
        phome = os.path.join(os.getenv('JUPYTER_SERVER_ROOT', '/home/jovyan'), 'projects')
        fn = os.path.join(phome, 'projects.json')
        if os.path.exists(fn):
            #    print("LOAD FROM FILE", fn)
            with open(fn, 'r') as infile:
                project_dict = json.load(infile)
                data = project_dict[PID]
                if not "name" in data:
                    logger.info(f"Unexpected response: {data}")
                    self.redirect(f"{fullurl}lab/tree/")
                projname = data["name"]
                projdir = str(PID) + '_' + slugify(project)
                for t in data["tasks"]:
                    if t == TID:
                        if t["name"] is None:
                            t["name"] = str(t["id"])
                        taskdir = str(idx) + '_' + slugify(t["name"]) # + '_(' + str(t['id'])[0:8] + ')'
                        break
                return self.redirect(f"{fullurl}lab/tree/projects/{projdir}/{taskdir}")
        else:
            #Can't get name data, just use PID and TID, create symlink first
            tpath = f"/mnt/project/{PID}/task/TID"
            lnpath = os.path.join(phome, str(PID))
            os.makedirs(lnpath, exist_ok=True)
            lnpath = os.path.join(lnpath, TID)
            os.symlink(tpath, lnpath)
            return self.redirect(f"{fullurl}lab/tree/projects/{PID}/{TID}")

class TokensHandler(tornado.web.RequestHandler):
    def get(self):
        logger.info("Handling tokens")
        tokens = self.application.tokens
        #Return the token data
        import jwt
        id_jwt = tokens.get("id_token")
        decoded = jwt.decode(id_jwt, options={"verify_signature": False}) # works in PyJWT >= v2.0
        logger.info(f"DECODED: {decoded}")
        id_token = decoded

        #Check if it is expired
        dt = datetime.datetime.fromtimestamp(tokens['expires_at'])
        #Need to decode the access_token as id_token expiry doesn't matter after initial verification
        #access = jwt.decode(tokens['access_token'], options={"verify_signature": False})
        #its = int(id_token['exp'])
        #idt = datetime.datetime.fromtimestamp(its)
        #ats = int(access['exp'])
        #adt = datetime.datetime.fromtimestamp(ats)
        now = datetime.datetime.now(tz=None)
        #userinfo += "\nExpires:" + dt.strftime("%d/%m/%Y %H:%M:%S")
        #userinfo += "\nID expires:" + idt.strftime("%d/%m/%Y %H:%M:%S")
        #userinfo += "\nAccess expires:" + adt.strftime("%d/%m/%Y %H:%M:%S")
        #userinfo += "\nNow:" + now.strftime("%d/%m/%Y %H:%M:%S")

        #Renew expired token
        if dt <= now:
            logger.info("EXPIRED!")
            #TODO: use refresh_token to get new token if necessary
            token_endpoint = f'{provider_url}/oauth/token'
            rtoken = tokens["refresh_token"]
            if rtoken and client:
                new_tokens = client.refresh_token(token_endpoint, refresh_token=rtoken)
                logger.info(f"NEW_TOKENS: {new_tokens}")
                tokens = new_token

        self.write(tokens)

class CallbackHandler(tornado.web.RequestHandler):
    def get(self):
        #NEW HANDLER - Authorization Code Flow with PKCE
        logger.info("CALLBACK")
        authorization_response = self.request.uri
        logger.info(authorization_response)
        token_endpoint = f'{provider_url}/oauth/token'
        logger.info(token_endpoint)
        logger.info(code_verifier)
        logger.info(state)
        #This gets the token using auth code flow
        tokens = client.fetch_token(token_endpoint, authorization_response=authorization_response, code_verifier=code_verifier, state=state)
        self.application.tokens = tokens #Store on application
        logger.info(tokens)

        #Re-write the input data, now include the server port to access tokens with
        utils.write_inputs(projects=projects, tasks=tasks, port=sys.argv[1])

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
            (r"/browse", BrowseHandler),
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


