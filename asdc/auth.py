"""
# OAuth2 login in Jupyter Notebooks

This module provides a way to login to an oauth2 provider and get an access_token from inside a jupyter environment

It has only been tested on the Auth0 provider for the Australian Scalable Drone Cloud project,
If it will work with other providers and scenarios is not known.

- Borrows code from and uses same techniques as ipyauth (https://oscar6echo.gitlab.io/ipyauth/) but without the widget
- Use popup or iframe to send the request 
- Listen for callback with a custom server behind jupyter-server-proxy - this provides a stable URL to configure as
  a callback at https://MY-JUPYTERHUB/jupyterhub_oauth2/callback, this is required by Auth0 as we can't have a wildcard port
  in the configured callback url.
- Receive token with another server behind jupyter-server-proxy within the calling environment,
  allowing user API calls to get/use the token

## Usage

```
import asdc

config = {
    "default_baseurl": 'https://JUPYTERHUB_URL/user-redirect',
    "api_audience": 'https://MYSITE/api',
    "api_client_id": 'CLIENT_ID_HERE',
    "api_device_client_id": 'DEVICE_CLIENT_ID_HERE',
    "api_scope": 'openid profile email',
    "api_authurl": 'MY_OAUTH2_PROVIDER_URL',
}

#Pass the config dict above (this can also be loaded from environment variables)
asdc.auth.setup(config)

#Connect to the OAuth2 provider, default is to open a new window for the login
await asdc.connect()

#Display info about a logged in user
asdc.showuserinfo()

#Call an API with GET
r = asdc.call_api('/projects/')
print(r.json())

#Call an API with POST
data = {'name': 'My Project', 'description': 'Created by API with token'}
r = asdc.call_api('/projects/', data)
print(r.json())

```
"""

import requests
import json
import os
import logging
import datetime
import time
import sys
from pathlib import Path
import jwt
from asdc.utils import read_inputs    #Utility functions

baseurl = ''      #Base jupyterhub url
access_token = '' #Store the received token here
token_data = ''   #All the received token data
port = None       #Server port, default is to automatically assign
nonce = ''        #For verifying token
_server = None     #Server to receive token
cookies = None

#Settings, to be provided before use
settings = {
    "default_baseurl": 'http://localhost:8888/',
    "api_audience": 'https://MYSITE/api',
    "api_client_id": '',
    "api_device_client_id": '',
    "api_scope": 'openid profile email',
    "api_authurl": 'MY_OAUTH2_PROVIDER_URL',
    #"token_prefix": 'JWT',
    "token_prefix": 'Bearer',
    "provided" : False
}

def setup(config=None):
    """Pass a dict with the authentication settings

    eg:
    >>> from asdc import auth
    ... auth.setup({"default_baseurl": 'https://JUPYTERHUB_URL/user-redirect',
    ...    "api_audience": 'https://MYSITE/api',
    ...    "api_client_id": 'CLIENT_ID_HERE',
    ...    "api_device_client_id": 'DEVICE_CLIENT_ID_HERE',
    ...    "api_scope": 'openid profile email',
    ...    "api_authurl": 'MY_OAUTH2_PROVIDER_URL'
     ...   })

    Parameters
    ----------
    config: dict
        The configuration dict
    """
    global settings
    if config is None:
        #Try and load from env variables
        # load .env first if exists
        from dotenv import load_dotenv
        envhome = str(Path.home() / '.env')
        if os.path.exists(envhome):
            load_dotenv(envhome)
        if os.path.exists('.env'):
            load_dotenv()
        try:
            settings["default_baseurl"] = os.getenv('JUPYTERHUB_URL', 'http://localhost:8888')
            if not "localhost" in settings["default_baseurl"]:
                settings["default_baseurl"] += '/user-redirect'
                #Using a named server?
                servername = os.getenv('JUPYTERHUB_SERVER_NAME', '')
                if len(servername):
                    settings["default_baseurl"] += '/' + servername
            settings["api_audience"] = os.getenv('JUPYTER_OAUTH2_API_AUDIENCE', 'https://asdc.cloud.edu.au/api')
            settings["api_client_id"] = os.getenv('JUPYTER_OAUTH2_CLIENT_ID', '')
            settings["api_device_client_id"] = os.getenv('JUPYTER_OAUTH2_DEVICE_CLIENT_ID', '')
            settings["api_scope"] = os.getenv('JUPYTER_OAUTH2_SCOPE', settings["api_scope"])
            settings["api_authurl"] = os.getenv('JUPYTER_OAUTH2_AUTH_PROVIDER_URL', '')
            settings["token_prefix"] = os.getenv('JUPYTER_OAUTH2_PREFIX', settings["token_prefix"])
            settings["provided"] = True
        except Exception as e:
            logging.error("Error loading settings from env: ", str(e))
    else:
        settings.update(config)
        settings["provided"] = True

def _check_settings():
    if not settings['provided']:
        print('Please call .setup(dict) to configure before use, defaults are not usable:\n', settings)
        raise(Exception('Settings not provided'))

async def check_server(url):
    """
    Test a server is working, will raise exception if request fails

    Parameters
    ----------
    url: str
        url to test
    """
    logging.info("Testing url: ", url)

    r = requests.get(U)

    if r.status_code >= 400:
        logging.info("Server responded error: {} {}".format(r.status_code, r.reason))
        raise(Exception("Server responded with error"))
    else:
        logging.info("Server responded OK: {} {}\n{}".format(r.status_code, r.reason, r.text))

async def _serve():
    """
    Listen for the token passed by browser on client side
    (Tried using websockets here, but wss: connections are not handled by jupyter-server-proxy)
    
    See: https://notebook.community/knowledgeanyhow/notebooks/hacks/Webserver%20in%20a%20Notebook
    """
    global settings, port, token_data, _server
    import tornado.ioloop
    import tornado.web
    import tornado.httpserver

    #Stop any existing server
    if _server:
        await stop_server()

    def set_token(data, verify=True):
        global nonce, token_data
        logging.debug("Verfifying, nonce: ", nonce, ", verify enabled: ",verify)
        if verify and data['id_token']['nonce'] != nonce:
            logging.error("INVALID TOKEN! Nonce does not match")
            token_data = None
        else:
            if verify:
                logging.debug("==> TOKEN VALIDATED!")
            else:
                logging.debug("==> TOKEN Reused, already validated")
            token_data = data

    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            #'''Renders the template with a title on HTTP GET.'''
            #self.finish(page.render(title='Tornado Demo'))
            #Just confirm server is running
            self.finish('OK')

    class TokenHandler(tornado.web.RequestHandler):
        def post(self):
            import json
            data = self.request.body
            t = json.loads(data)
            logging.debug("==> TOKEN RECEIVED via POST")
            set_token(t)
            self.finish("Token processed")

        def get(self):
            import json
            import base64
            logging.debug("==> TOKEN RECEIVED via GET")
            data = self.get_argument("data", default=None, strip=False)
            verify = self.get_argument("verify", default="True", strip=False)
            t = json.loads(base64.b64decode(data).decode('utf-8'))
            set_token(t, verify == "True") #Can't verify when reusing token as nonce may have been cleared
            self.finish("Token processed")

    application = tornado.web.Application([
        (r"/", MainHandler),
        (r"/token", TokenHandler)
    ])

    #Selects a random port by default,
    #allowing multiple notebooks to use this without conflicts
    _server = tornado.httpserver.HTTPServer(application)
    _server.listen(port, '0.0.0.0')
    
    #Get the actual port assigned
    if port is None:
        #(First entry in _sockets)
        socket = _server._sockets[next(iter(_server._sockets))]
        port = socket.getsockname()[1]

    logging.debug("Running on port: ", port) 

def _listener():
    """ Setup the listener to receive reponse message posted from popup or iframe
    that processes the oauth2 request
    """
    global settings, baseurl, port, access_token, token_data
    if not baseurl:
        _check_settings()
        baseurl = settings["default_baseurl"]
        logging.info("Base url: ", baseurl)

    from IPython.display import display, HTML
    from string import Template
    temp_obj = Template("""
    <script>
    //Have the token, send back to server with HTTP POST
    function postToken_$PORT(data) {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", '$BASEURL/proxy/$PORT/token', true);
        //Send the proper header information along with the request
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onload = function() {console.log('postToken successful');}
        xhr.send(JSON.stringify(data));
    }

    //Have the token, send back to server with HTTP GET
    function postTokenGET_$PORT(data, reuse) {
        var xhr = new XMLHttpRequest();
        var encoded = window.btoa(JSON.stringify(data));
        var uri = '$BASEURL/proxy/$PORT/token?data=' + encoded;
        if (reuse)
            uri += '&verify=False';
        xhr.open("GET", uri);
        xhr.onload = function() {console.log('postTokenGET successful');}
        xhr.send();
    }

    //Get message from iframe or popup
    function message_received(event) {
        //console.log("ORIGIN:" + event.origin);
        //console.log("MESSAGE:" + JSON.stringify(event.data));
        if ("access_token" in event.data) {
            //Save token on client side
            window.token = event.data;

            //POST gets 405 method not allowed on jupyterhub
            //postToken_$PORT(event.data);
            postTokenGET_$PORT(event.data);

            //Stop listening after sending token
            window.removeEventListener('message', self);
            //window.listenerExists = false;

            //Close iframe if any
            document.querySelectorAll('.asdc-oauth-frame').forEach(e => e.remove());
        } else {
            //Show iframe if any
            document.querySelectorAll('.asdc-oauth-frame').forEach(e => e.style.height = '300px');
        }
    }
    window.addEventListener("message", message_received);
    </script>
    """)
    script = temp_obj.substitute(BASEURL=baseurl, PORT=str(port))
    display(HTML(script))

def _send(mode='iframe'):
    """ Open auth request page with iframe / popup / link and listen for postMessage 
    
    Parameters
    ----------
    mode : str
        'popup' opens page in new window/tab (may require disabling popup blockers)
        'iframe' opens page in inline iframe (this seems less reliable)
        'link' displays link to the auth page without opening it automatically
    """
    import urllib
    #This uses jupyter-server-proxy entry-point magic to provide a consistent callback url
    redirect = baseurl + '/asdc/callback'
    import secrets
    global nonce, port
    nonce = secrets.token_urlsafe(nbytes=8)
    f = {'response_type' : 'token id_token',
         'redirect_uri' : redirect,
         'client_id' : settings["api_client_id"],
         'audience' : settings["api_audience"],
         'scope' : settings["api_scope"],
         'nonce' : nonce,
         'state' : 'auth0,' + nonce,
         #'state' : 'auth0,iframe,' + nonce,
         #'state' : 'auth0,popup,' + nonce,
         #'prompt' : 'none'}
        }
    logging.debug("Auth query params: ", f)
    #print("Auth query params: ", f)
    query = urllib.parse.urlencode(f)
    authurl = settings["api_authurl"] + '/authorize?' + query

    from IPython.display import HTML
    from string import Template
    temp_obj = Template("""<script>
    //This code only has 10 seconds to run after the output produced
    //(Prevents re-running from saved notebook output)
    var now = new Date().getTime();
    var ts = new Date(document.getElementById('$ID').dataset.timestamp * 1000);
    if (now - ts < 10000) {
        var mode = "$MODE";
        if (window.token) {
            var now = new Date().valueOf();
            var tokens = window.token['access_token'].split(".");
            var access = JSON.parse(atob(tokens[1]));
            console.log("ID Token expired?: " + (window.token['id_token']['exp']*1000 <= now));
            console.log("Access Token expired?: " + (access['exp']*1000 <= now));
            if (window.token['id_token']['exp']*1000 > now && access['exp']*1000 > now) {
                //Use saved token on client side
                postTokenGET_$PORT(window.token, true); //Pass re-use flag to skip verification
            } else {
                //Clear expired tokens
                window.token = null;
            }
        }

        function show_frame() {
            var frames = document.querySelectorAll('.asdc-oauth-frame');
            if (frames.length) {
                frames.forEach(e => e.style.height = '300px');
                //Try popup
                window.open("$URL");
            }
        }

        if (!window.token) {
            var alt = '(Automatic authentication via $MODE processing, <a href="$URL" target="_blank" rel="opener">click here</a> to login manually)';
            if (mode == 'popup') {
                window.open("$URL");
                html = alt;
            } else if (mode == 'iframe') {
                html = '<iframe class="asdc-oauth-frame" src="$URL" style="width: 400px; height: 0px; border: 0;"></iframe><br>' + alt;
                setTimeout(show_frame, 5000); //Show the frame if still there after 5 seconds
            } else if (mode == 'iframe_debug') {
                html = '<iframe src="$URL" width="400px" height="300px" style="border:1px solid #ccc;"></iframe><br>' + alt;
            } else if (mode == 'link') {
                html = '<h3><a href="$URL" target="_blank" rel="opener">Click here to login</a></h3>';
            }
            document.getElementById('$ID').innerHTML = html;
        }
    } else {
      console.log("Fragment expired, skipping run: " + new Date(now).toUTCString() + " : " + new Date(ts).toUTCString());
    }
    </script>
    <div id="$ID" data-timestamp="$NOW"></div>
    """)
    script = temp_obj.substitute(URL=authurl, ID="auth_" + nonce, MODE=mode, PORT=port, NOW=str(int(time.time())))
    display(HTML(script))

def is_notebook():
    """
    Detects if running within an interactive IPython notebook environment

    Returns
    -------
    boolean
        True if IPython detected and browser/notebook display capability detected
    """
    if 'IPython' not in sys.modules:
        # IPython hasn't been imported, definitely not
        return False
    try:
        from IPython import get_ipython
        from IPython.display import display,Image,HTML
    except:
        return False
    # check for `kernel` attribute on the IPython instance
    return getattr(get_ipython(), 'kernel', None) is not None

def authenticate(config=None, scope=""):
    """
    Calls the server endpoint to get preloaded OAuth2 tokens
    - If tokens have expired they should automatically have been refreshed

    Parameters
    ----------
    config: dict
        The configuration dict, required if .setup() has not yet been called to
        provide the settings.
    scope : str
        Any additional scopes to append to default list ('openid profile email' unless overridden)
    """
    global settings, baseurl, port, access_token, token_data
    if not baseurl:
        _check_settings()
        baseurl = settings["default_baseurl"]
        logging.info("Base url: ", baseurl)

    #Get the local port of the server instance
    #(If not found, wait for authentication via popup or user action)
    data = read_inputs()
    port = data["port"]
    if port is None:
        #Server not yet started, provide a button to manually authenticate
        if is_notebook():
            # A bit of a hack: create a html button that opens auth url
            # add an on_click that finds a unique ipywidgets button and
            # call it's click() event to run the server side code
            import uuid
            uid = str(uuid.uuid4())
            from IPython.display import display, HTML
            import ipywidgets as widgets
            r_url = settings["default_baseurl"] + '/asdc/redirect?path=nowhere'
            html = """<script>
            function click_it() {
                let button = document.getElementsByClassName("UID")[0];
                button.click();
            }
            </script>
            <a href='URL' target='_blank' onclick='click_it();' class='jupyter-button widget-button'>Authenticate</a>
            """.replace("UID", uid).replace("URL", r_url)

            btn = widgets.Button(description="hidden")
            btn.layout.display = 'none' #Hide the widget
            btn.add_class(uid) #Add unique class id
            out = widgets.Output()
            def window_open_button(url):
                with out:
                    timeout_seconds=10
                    import asyncio
                    print('Waiting for authorisation', end='')
                    data = read_inputs()
                    port = data["port"]
                    for i in range(0,timeout_seconds*4): #4 ticks per second
                        #Have the port yet?
                        if port:
                            authenticate()
                            break
                        #Blocking sleep
                        time.sleep(0.25)
                        #Visual feedback
                        print('.', end='')
                        sys.stdout.flush()
                        #Attempt to load port again
                        data = read_inputs()
                        port = data["port"]
            btn.on_click(window_open_button)
            display(btn, out, HTML(html))

        print("Auth tokens not yet available ...")
        return

    if config is not None:
        setup(config)
    _check_settings()

    if scope is not None:
        settings["api_scope"] += " " + scope

    #Have a token already? Check if it is expired
    if token_data:
        dt = datetime.datetime.fromtimestamp(token_data['expires_at'])
        now = datetime.datetime.now(tz=None)
        #print("Token expires:", dt.strftime("%d/%m/%Y %H:%M:%S"))
        #print("Now:", now.strftime("%d/%m/%Y %H:%M:%S"))

        #Renew expired token
        if dt <= now:
            token_data = None

    #Send the token request
    if not token_data:
        server = f"http://localhost:{port}/tokens"
        r = requests.get(server, headers={'Content-type': 'application/json'})

        if r.status_code >= 400:
            logging.info("Server responded error: {} {}".format(r.status_code, r.reason))
            raise(Exception("Server responded with error"))
        else:
            logging.info("Server responded OK: {} {}".format(r.status_code, r.reason))
            token_data = r.json()

        if not token_data:
            raise(Exception("Unable to retrieve access token! "))

        access_token = token_data['access_token']

    else:
        print('Already have a valid token')

async def connect(config=None, mode='iframe', timeout_seconds=30, scope=""):
    """
    Authenticate with the OAuth2 id provider

    - Starts the server, calls the auth api and awaits token (default 30 sec timeout).
    - Requires a configuration dict or setup() to be called first with the auth settings dict.
    - Must be called with await as uses asyncio.sleep while the token is retrieved.
    - If the timeout passes you can still complete the login/auth process and the token should
      be available when it completes.

    eg:

    >>> import jupyter_oauth2_api as auth
    ... await auth.connect({"default_baseurl": 'https://JUPYTERHUB_URL/user-redirect',
    ...    "api_audience": 'https://MYSITE/api',
    ...    "api_client_id": 'CLIENT_ID_HERE',
    ...    "api_scope": 'openid profile email',
    ...    "api_authurl": 'MY_OAUTH2_PROVIDER_URL',
    ...    "provided" : False
    ...   })
    ... print(auth.access_token)
    
    Parameters
    ----------
    config: dict
        The configuration dict, required if .setup() has not yet been called to
        provide the settings.
    mode : str
        'popup' opens page in new window/tab (may require disabling popup blockers)
        'iframe' opens page in inline iframe (this seems to be unreliable)
        'link' displays link to the auth page without opening it automatically
    timeout_seconds: int
        Seconds to wait for the authentication process to complete before
        raising an exception
    scope : str
        Any additional scopes to append to default list ('openid profile email' unless overridden)
    """
    print("'await asdc.connect()' is deprecated, you can remove this line from your code")
    return authenticate()

    global settings, access_token, token_data, _server
    if config is not None:
        setup(config)
    _check_settings()

    if scope is not None:
        settings["api_scope"] += " " + scope

    #Have a token already? Check if it is expired
    if token_data:
        #Need to decode the access_token as it seems it expires earlier than id_token
        access = jwt.decode(token_data['access_token'], options={"verify_signature": False})
        its = int(token_data['id_token']['exp'])
        idt = datetime.datetime.fromtimestamp(its)
        ats = int(access['exp'])
        adt = datetime.datetime.fromtimestamp(ats)
        now = datetime.datetime.now(tz=None)
        #print("ID expires:", idt.strftime("%d/%m/%Y %H:%M:%S"))
        #print("Access expires:", adt.strftime("%d/%m/%Y %H:%M:%S"))
        #print("Now:", now.strftime("%d/%m/%Y %H:%M:%S"))

        #Renew expired token
        if idt <= now or adt <= now:
            token_data = None

    #Setup the server, listener and send the auth request
    if not token_data:
        await _serve()
        _listener()
        _send(mode)

        import asyncio
        import time
        import sys
        print('Waiting for authorisation', end='')
        for i in range(0,timeout_seconds*4): #4 ticks per second
            #Have the token yet?
            if token_data: break
            #Async sleep to allow server to process requests
            await asyncio.sleep(0.25)
            #Blocking sleep to actually pause processing
            time.sleep(0.25)
            #Visual feedback
            print('.', end='')
            sys.stdout.flush()
    
        if not token_data:
            await stop_server()
            raise(Exception("Timed out awaiting access token! "))
        else:
            print('.. success.')

        access_token = token_data['access_token']

        await stop_server()
    else:
        print('Already have a valid token')

async def stop_server():
    """Stop the server
    Called automatically upon recieving token except in case of timeout
    """
    global _server, port
    await _server.close_all_connections()
    _server.stop()
    _server = None
    port = None

def device_connect(config=None, qrcode=True, browser=False, scope=""):
    """
    Authenticate with the OAuth2 id provider using the device auth flow

    This requires a different type of application and a new client_id on Auth0,
    (Native app with device code grant enabled)

    Thanks to Joe Parks for the code example:
    https://gitlab.com/oscar6echo/ipyauth/-/issues/8#note_837687415

    See also:
    - https://auth0.com/docs/get-started/authentication-and-authorization-flow/device-authorization-flow
    - https://auth0.com/docs/get-started/authentication-and-authorization-flow/call-your-api-using-the-device-authorization-flow

    - Calls the auth api and awaits token,
      requires user to click a link and authorise in the browser.
    - Requires a configuration dict or setup() to be called first with the auth settings dict.

    eg:

    >>> import jupyter_oauth2_api as auth
    ... await auth.connect_device({"api_audience": 'https://MYSITE/api',
    ...    "api_device_client_id": 'DEVICE_CLIENT_ID_HERE',
    ...    "api_scope": 'openid profile email',
    ...    "api_authurl": 'MY_OAUTH2_PROVIDER_URL'
    ...   })
    ... print(auth.access_token)

    Parameters
    ----------
    config: dict
        The configuration dict, required if .setup() has not yet been called to
        provide the settings.
    qrcode: bool
        Attempt to output a QR code with the auth url
        Requires the qrcode python module
    scope : str
        Any additional scopes to append to default list ('openid profile email' unless overridden)
    """
    global settings, access_token, token_data, _server
    if config is not None:
        setup(config)
    _check_settings()

    #If no specific device_client_id, assume the client_id is enabled for this flow
    if len(settings["api_device_client_id"]) == 0:
        settings["api_device_client_id"] = settings["api_client_id"]

    if scope is not None:
        settings["api_scope"] += " " + scope

    if qrcode:
        #Disable qrcode if module not installed
        try:
            import io
            import qrcode
            from PIL import Image
        except (ImportError) as e:
            qrcode = False
            pass

    headers = {
        "content-type": "application/x-www-form-urlencoded",
    }
    data = {
        "client_id": settings['api_device_client_id'],
        "scope": settings['api_scope'],
        "audience": settings['api_audience']
    }

    AUTH_DOMAIN = settings['api_authurl']
    response = requests.post(f"{AUTH_DOMAIN}/oauth/device/code", headers=headers, data=data)
    if response.status_code >= 500 or "error" in response.json():
        print(response.json())
        return

    logging.info(response.json())
    user_code = response.json()["user_code"]
    verify_url = response.json()["verification_uri_complete"]
    device_code = response.json()["device_code"]
    if is_notebook():
        from IPython.display import display, HTML

        display(f"Click link below to authenticate (verify code={user_code})")
        display(HTML(f'<h1>{user_code}</h1><a href="{verify_url}" target="_blank">{verify_url}</a>'))
        if qrcode:
            qr = qrcode.make(verify_url, box_size=5)
            display(qr)
    else:
        print(f"Click or copy link below to authenticate (verify code={user_code})")
        print(" _______________ ")
        print("|               |")
        print('|   \033[1m' + user_code + '\033[0m   |')
        print("|_______________|\n")
        print(verify_url)
        if qrcode:
            qr = qrcode.QRCode()
            qr.add_data(verify_url)
            qr.print_ascii()

    if browser:
        import webbrowser
        webbrowser.open(verify_url)

    headers2 = {
        "content-type": "application/x-www-form-urlencoded",
    }
    data2 = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": settings['api_device_client_id'],
    }

    logged_in = False
    token = {}
    while not logged_in:
        time.sleep(2)
        token = requests.post(f"{AUTH_DOMAIN}/oauth/token", headers=headers2, data=data2)
        if token.status_code == 200:
            if is_notebook():
                from IPython.display import display

                display(f"Successfully authenticated!")
            else:
                print("Successfully authenticated!")
                logged_in = True
        token_json = token.json()
        if "access_token" in token_json:
            access_token = token_json["access_token"]
            break

def local_connect(config=None, mycookies=None):
    if config is not None:
        setup(config)
    _check_settings()
    #Experimental path for calling ASDC API from local or virtual desktop in python
    # - open browser (I had issues with chrome in browser_cookie3, had to use firefox)
    # - go to https://dev.asdc.cloud.edu.au and login
    # - run this script
    #You can pass in the cookies if you want to use an alternate method of getting them

    #Get the cookies from default session in firefox/chrome/all browsers
    global cookies
    if mycookies:
        cookies = mycookies
    else:
        import browser_cookie3
        from urllib.parse import urlparse
        domain = urlparse(settings["api_audience"]).netloc
        #cookies = browser_cookie3.firefox(domain_name='dev.asdc.cloud.edu.au') #Firefox
        #cookies = browser_cookie3.chrome(domain_name='dev.asdc.cloud.edu.au') #Chrome
        #cookies = browser_cookie3.load() #All avail browsers
        cookies = browser_cookie3.load(domain_name=domain)

