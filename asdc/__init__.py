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
import pathlib
from slugify import slugify

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
auth.setup()

#Utility functions
def call_api(url, data=None, headersAPI=None, content_type='application/json', throw=False, prefix=auth.settings["token_prefix"]):
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
    if headersAPI is None:
        headersAPI = {
        'accept': 'application/json',
        'Content-type': content_type,
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
        print(r.status_code, r.reason, url)
        if throw:
            raise(Exception("Error response from server!"))
    #print(r.text)
    return r

def download(url, filename=None, block_size=8192, overwrite=False, throw=False, prefix=auth.settings["token_prefix"]):
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

    if not overwrite and os.path.exists(filename):
        print("File exists: " + filename)
        return filename

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

def download_asset(project, task, filename, overwrite=False):
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
    download('/projects/{PID}/tasks/{TID}/download/{ASSET}'.format(PID=project, TID=task, ASSET=filename), overwrite=overwrite)

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

def create_links(src='/mnt/project', dest='/home/jovyan/projects'):
    """
    Create symlinks with nicer names for mounted projects and tasks

    Assumes by defailt projects are mounted at /mnt/project/PID/tasks/TID,
    will create project folder in home dir with links using project
    names and task names
    """

    #1) Get the mounted projects list
    prjfolders = [ f.path for f in os.scandir(src) if f.is_dir() ]

    audience = auth.settings["api_audience"]
    if auth.access_token:
        #Can use authenticated API for each mounted project
        url = f"{audience}/plugins/asdc/projects/{PID}/gettasks"
        jsondata = None
    else:
        #Use the public API, requires valid username, returns all projects
        user = os.getenv('JUPYTERHUB_USER', '')
        url = auth.settings["api_audience"] + "/plugins/asdc/usertasks?email=" + user
        response = requests.get(url, timeout=10)
        jsondata = response.json()

    #2) Iterate projects....
    for pf in prjfolders:
        ppath = Path(pf)
        PID = ppath.name

        #Use provided project/task data or call the API
        if jsondata:
            data = jsondata[PID]
        else:
            #response = requests.get(url, timeout=10)
            response = call_api(url) #Use authenticated endpoint
            data = response.json()
        if not "name" in data:
            print("Unexpected response: ", data)
            return

        projname = data["name"]

        #2b)  - Create dir $HOME/project/ with verbose name (use python-slugify)
        #Append ID to handle projects with duplicate name
        projdir = str(PID) + '_' + slugify(projname)
        #projdir = str(PID).zfill(5) + '_' + slugify(projname)
        try:
            os.makedirs(dest + '/' + projdir, exist_ok=True)
        except (FileExistsError) as e:
            pass

        #3) Get the tasks per project using api url above from plugin
        #3a iterate tasks
        #Append index to handle tasks with duplicate names
        idx = 1
        #ntasks = len(data["tasks"]
        #fill = math.floor(math.log10(ntasks)) + 1 #Calculate zero padding required
        for t in data["tasks"]:
            if t["name"] is None:
                t["name"] = str(t["id"])
            tpath = ppath / "task" / str(t['id'])
            lnpath = dest + '/' + projdir + '/' + str(idx) + '_' + slugify(t["name"]) # + '_(' + str(t['id'])[0:8] + ')'
            #lnpath = dest + '/' + projdir + '/' + str(idx).zfill(fill) + '_' + slugify(t["name"]) # + '_(' + str(t['id'])[0:8] + ')'
            #Remove any existing file/link
            try:
                os.remove(lnpath)
            except (FileNotFoundError) as e:
                pass
            #3b create symlink for task using same function as above
            os.symlink(tpath, lnpath)
            idx += 1


