"""
# ASDC API v0.1

## Australian Scalable Drone Cloud data access API module

### Initial goals:

- Get tokens to access the WebODM API at https://asdc.cloud.edu.au/api
- Provide convenience functions for calling above API
- Functions for moving drone data to and from cloud storage services, S3, CloudStor etc

"""
#See also: https://github.com/localdevices/odk2odm/blob/main/odk2odm/odm_requests.py

import requests
import json
import os

# This is the server process launched by installed entrypoint
# Whenever request is made on (jupyterhub_url)/asdc this server is started
# if not running, then processes the request
# https://jupyter-server-proxy.readthedocs.io/en/latest/server-process.html
def setup_asdc():
  return {
    'command': ['python', '-m', 'asdc.server', '{port}', '{base_url}'],
  }

import asdc.auth as auth    #For back compatibility
from asdc.auth import *     #Also now available in root module

#Settings should be provided in env variables
import os
# load .env if vars not already in env
if not "JUPYTER_OAUTH2_CLIENT_ID" in os.environ:
    from dotenv import load_dotenv
    load_dotenv()

#Still not set? Just use some defaults (auth will not work)
if not "JUPYTER_OAUTH2_CLIENT_ID" in os.environ:
    os.environ['JUPYTERHUB_URL'] = 'https://jupyter.asdc.cloud.edu.au/user-redirect'
    os.environ['JUPYTER_OAUTH2_API_AUDIENCE'] = 'https://asdc.cloud.edu.au/api'
    os.environ['JUPYTER_OAUTH2_CLIENT_ID'] = 'CLIENT_ID_HERE'
    os.environ['JUPYTER_OAUTH2_SCOPE'] = 'openid profile email'
    os.environ['JUPYTER_OAUTH2_AUTH_PROVIDER_URL'] = 'https://au-scalable-drone-cloud.au.auth0.com/'

auth.setup()

#Utility functions
def call_api(url, data=None, throw=False, prefix=auth.settings["token_prefix"]):
    """
    Call an API endpoint

    Parameters
    ----------
    url: str
        endpoint url, either full uri or path / which will be appended to "api_audience" url from settings
    data: dict
        json data for a POST request, if omitted will send a GET request
    throw: bool
        throw exception on http errors, default: False

    Returns
    -------
    object
        http response object
    """
    if url[0:4] != "http":
        #Prepend the configured api url
        url = auth.settings["api_audience"] + url

    #WebODM api call
    headersAPI = {
    'accept': 'application/json',
    'Content-type': 'application/json',
    'Authorization': prefix + ' ' + auth.access_token if auth.access_token else '',
    }
    
    #POST if data provided, otherwise GET
    if data:
        r = requests.post(url, headers=headersAPI, json=data)
    else:
        r = requests.get(url, headers=headersAPI)
    
    #Note: if response is 403 Forbidden {'detail': 'Username not available'}
    # this is because the user hasn't logged in to the main site yet with this auth method
    # (ie: originally logged in with github, use AAF to auth with jupyter)
    if r.status_code >= 400:
        print(r.status_code, r.reason)
        if throw:
            raise(Exception("Error response from server!"))
    #print(r.text)
    return r

def download(url, filename=None, block_size=8192, throw=False, prefix=auth.settings["token_prefix"]):
    """
    Call an API endpoint to download a file

    Parameters
    ----------
    url: str
        endpoint url, either full uri or path / which will be appended to "api_audience" url from settings
    filename: str
        local filename, if not provided will use the filename from the url
    block_size: int
        size of chunks to download
    throw: bool
        throw exception on http errors, default: False

    Returns
    -------
    str
        local filename saved
    """
    if url[0:4] != "http":
        #Prepend the configured api url
        url = auth.settings["api_audience"] + url

    #WebODM api call
    headersAPI = {
    'accept': 'application/json',
    'Content-type': 'application/json',
    'Authorization': prefix + ' ' + auth.access_token if auth.access_token else '',
    }

    if filename is None:
        filename = url.split('/')[-1]

    #Progress bar
    if auth.is_notebook():
        from tqdm.notebook import tqdm
    else:
        import tqdm

    # NOTE the stream=True parameter below
    #https://stackoverflow.com/a/16696317
    with requests.get(url, headers=headersAPI, stream=True) as r:
        total_size_in_bytes= int(r.headers.get('content-length', 0))
        progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True)
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=block_size):
                progress_bar.update(len(chunk))
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk:
                f.write(chunk)
        progress_bar.close()
        if total_size_in_bytes != 0 and progress_bar.n != total_size_in_bytes:
            print("ERROR, something went wrong")
    return filename

def download_asset(project, task, filename):
    """
    Call WebODM API endpoint to download an asset file

    Parameters
    ----------
    project: int
        project ID
    task: str
        task ID
    filename: str
        asset filename to download
    """
    download('/projects/{PID}/tasks/{TID}/download/{ASSET}'.format(PID=project, TID=task, ASSET=filename))

def call_api_js(url, callback="alert()", data=None, prefix=auth.settings["token_prefix"]):
    """
    Call an API endpoint from the browser via Javascript, appends a script to the page to 
    do the request.

    Parameters
    ----------
    url: str
        endpoint url, either full uri or path / which will be appended to "api_audience" url from settings
    callback: str
        javascript code defining a callback function
    data: dict
        json data for a POST request, if omitted will send a GET request
    """
    #GET, list nodes, passing url and token from python
    from IPython.display import display, HTML
    #Generate a code to prevent this call happening again if page reloaded without clearing
    import string
    import secrets
    alphabet = string.ascii_letters + string.digits
    code = "req_" + ''.join(secrets.choice(alphabet) for i in range(8))
    method = "POST"
    if data is None:
        method = "GET"
        data = {}
    from string import Template
    temp_obj = Template("""<script>
    //Prevent multiple calls
    if (!window._requests) 
      window._requests = {};
    if (!window._requests["$CODE"]) {
        var data = $DATA;
        var callback = $CALLBACK;
        var xhr = new XMLHttpRequest();
        xhr.open("$METHOD", "$URL");
        xhr.setRequestHeader("Authorization", "$PREFIX $TOKEN");
        //Can also just grab it from window...
        //xhr.setRequestHeader("Authorization", "$PREFIX " + window.token['auth.access_token']);
        xhr.responseType = 'json';
        xhr.onload = function() {
            // Request finished. Do processing here.
            var data = xhr.response;
            console.log('success');
            callback(xhr.response);
        }

        if (data && Object.keys(data).length) {
            var formData = new FormData();
            for (var key in data)
                formData.append(key, data[key]);

            xhr.send(formData);
        } else {
            xhr.send();
        }

        //Flag request sent
        window._requests["$CODE"] = true;
    }
    </script>
    """)
    script = temp_obj.substitute(DATA=json.dumps(data),
                CODE=code, METHOD=method, URL=url,
                TOKEN=auth.access_token, PREFIX=prefix, CALLBACK=callback)
    display(HTML(script))

def userinfo():
    """
    Call the userinfo API from Auth0 to get user details

    Returns
    -------
    dict
        json dict containing user info
    """
    r = call_api(auth.settings["api_authurl"] + '/userinfo') #, prefix='Bearer')
    data = r.json()
    return data

def showuserinfo():
    """
    Call the userinfo API from Auth0 and display username/email and avatar image inline
    """
    user = userinfo()
    #print(json.dumps(user, indent=4, sort_keys=True))
    print("Username: ", user["name"])
    from IPython.display import display, HTML
    display(HTML("<img src='" + user["picture"] + "' width='120' height='120'>"))


