"""
# ASDC API v0.1

## Australian Scalable Drone Cloud data access API module

### Initial goals:

- Get tokens to access the WebODM API at https://asdc.cloud.edu.au/api
- Provide convenience functions for calling above API
- Functions for moving drone data to and from cloud storage services, S3, CloudStor etc

"""
#See also: https://github.com/localdevices/odk2odm/blob/main/odk2odm/odm_requests.py

import json
import os
import re
import pathlib
import shutil
import zipfile
from slugify import slugify
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

# This is the server process launched by installed entrypoint
# Whenever request is made on (jupyterhub_url)/asdc this server is started
# if not running, then processes the request
# https://jupyter-server-proxy.readthedocs.io/en/latest/server-process.html
def setup_asdc():
  return {
    'command': ['python', '-m', 'asdc.server', '{port}', '{base_url}'],
    'timeout' : 20,
    #'launcher_entry' : {'enabled' : True, 'icon_path' : 'logo.svg', 'title' : 'ASDC'}
  }

import asdc.auth as auth    #For back compatibility
from asdc.auth import *     #Also now available in root module
auth.setup()
project_dir = os.path.join(os.getenv('JUPYTER_SERVER_ROOT', '/home/jovyan'), 'projects')

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
    if not r.ok:
        print(r.status_code, r.reason, url)
        if throw:
            raise(Exception("Error response from server!"))
    #print(r.text)
    return r

def download(url, filename=None, block_size=8192, data=None, overwrite=False, throw=False, progress=True, silent=False, prefix=auth.settings["token_prefix"]):
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
    progress: bool
        Show progress bar

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
    'Content-type': 'application/octet-stream',
    'Authorization': prefix + ' ' + auth.access_token if auth.access_token else '',
    }

    if filename is None:
        filename = url.split('/')[-1]

    if not overwrite and os.path.exists(filename):
        if not silent: print("File exists: " + filename)
        return filename

    #Progress bar
    if progress:
        if auth.is_notebook():
            from tqdm.notebook import tqdm
        else:
            import tqdm

    # NOTE the stream=True parameter below
    #https://stackoverflow.com/a/16696317
    #POST if data provided, otherwise GET
    if data:
        r = requests.post(url, headers=headersAPI, json=data, stream=True)
    else:
        r = requests.get(url, headers=headersAPI, stream=True)
    #with requests.get(url, headers=headersAPI, stream=True) as r:
    if not r.ok:
        if not silent: print("Error response:", r, url)
        return None
    else:
        total_size_in_bytes= int(r.headers.get('content-length', 0))
        got_bytes = 0
        if progress:
            progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True, leave=False)
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=block_size):
                got_bytes += len(chunk)
                if progress:
                    progress_bar.update(len(chunk))
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk:
                f.write(chunk)
        if progress:
            progress_bar.close()
        if total_size_in_bytes != 0 and got_bytes != total_size_in_bytes:
            print("ERROR, something went wrong")
    return filename

def download_asset(filename, dest=None, project=None, task=None, overwrite=False, progress=True):
    """
    Call WebODM API endpoint to download an asset file

    Parameters
    ----------
    filename: str
        asset filename to download
    dest: str
        destination filename, if omitted will use source filename
    project: int
        project ID
    task: str
        task ID
    progress: bool
        Show progress bar
    """
    #Use the default selections unless arg passed
    project, task = get_selection(project, task)

    res = download(f'/projects/{project}/tasks/{task}/download/{filename}', filename=dest, overwrite=overwrite, progress=progress, silent=True)
    #If it failed, try the raw asset url
    if res is None:
        #Raw asset download, needed for custom assets, but requires full path:
        #eg: orthophoto.tif => odm_orthophoto/odm_orthophoto.tif
        res = download(f'/projects/{project}/tasks/{task}/assets/{filename}', filename=dest, overwrite=overwrite, progress=progress)
    return res

def export_asset(asset, params, project=None, task=None, overwrite=False, progress=True):
    """
    Call WebODM API endpoints to export a converted asset file
    The existing asset file can be downloaded with the /download/fn endpoint

    Parameters
    ----------
    asset: str
        asset label to download
    params: dict
        params for conversion, eg:
        {
            "format": "LAZ",
            "epsg": "32615",
        }
    project: int
        project ID
    task: str
        task ID
    progress: bool
        Show progress bar


    data {
        format: ""
        epsg: "3112" / "4326"
    }

    #EPSG:
    <option value="32615">UTM (EPSG:32615)</option>
    <option value="4326">Lat/Lon (EPSG:4326)</option>
    <option value="3857">Web Mercator (EPSG:3857)</option>
    <option value="custom">Custom EPSG</option>

    #Orthophoto: orthophoto
    <option value="gtiff">GeoTIFF (Raw)</option>
    <option value="gtiff-rgb">GeoTIFF (RGB)</option>
    <option value="jpg">JPEG (RGB)</option>
    <option value="png">PNG (RGB)</option>
    <option value="kmz">KMZ (RGB)</option>

    #Surface Model: dsm
    <option value="gtiff">GeoTIFF (Raw)</option>
    <option value="gtiff-rgb">GeoTIFF (RGB)</option>
    <option value="jpg">JPEG (RGB)</option>
    <option value="png">PNG (RGB)</option>
    <option value="kmz">KMZ (RGB)</option>

    #Point cloud: georeferenced_model
    <option value="laz">LAZ</option>
    <option value="las">LAS</option>
    <option value="ply">PLY</option>
    <option value="csv">CSV</option>

    """
    #Use the default selections unless arg passed
    project, task = get_selection(project, task)

    #First post to /export, then get from the task
    res = call_api(f'/projects/{project}/tasks/{task}/{asset}/export', data=params)
    data = res.json()
    if 'celery_task_id' in data:
        # wait for the result to be available before continuing
        worker_id = data['celery_task_id']
        print("Processing request...", end='')
        timeout_seconds = 60
        result = {"ready": False}
        for i in range(0,timeout_seconds):
            time.sleep(1)
            #Check the status
            r = call_api(f'/workers/check/{worker_id}')
            result = r.json()
            if result["ready"]:
                break
            print('.', end='')
            sys.stdout.flush()
    
        if not result["ready"]:
            raise(Exception("Timed out awaiting result!"))
        else:
            print('.. done.')
            filename = data['filename']
            res = download(f'/workers/get/{worker_id}?filename={filename}', filename, overwrite=overwrite, progress=progress)

    return res

def upload(url, filepath, dest=None, block_size=8192, progress=True, throw=False, prefix=auth.settings["token_prefix"], **kwargs):
    """
    Call an API endpoint to upload a file

    Parameters
    ----------
    url: str
        endpoint url, either full uri or path / which will be appended to "api_audience" url from settings
    filepath: str
        file path to open and upload
    dest: str
        destination filename, if omitted will use source
    progress: bool
        Show progress bar
    block_size: int
        size of chunks to upload
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

    #Progress bar
    if progress:
        if auth.is_notebook():
            from tqdm.notebook import tqdm
        else:
            import tqdm

    #Pass any additional post data in kwargs
    fields = kwargs

    #https://stackoverflow.com/a/67726532
    path = pathlib.Path(filepath)
    total_size = path.stat().st_size
    if dest:
        filename = dest
    else:
        filename = path.name

    def do_upload(bar=None):
        with open(filepath, "rb") as f:
            fields["file"] = (filename, f)
            e = MultipartEncoder(fields=fields)
            data = e
            if bar:
                m = MultipartEncoderMonitor(e, lambda monitor: bar.update(monitor.bytes_read - bar.n))
                data = m
            headers = {'Content-Type': data.content_type,
                       'Authorization': prefix + ' ' + auth.access_token if auth.access_token else ''}
            return requests.post(url, data=data, headers=headers)

    if progress:
        with tqdm(desc=filename, total=total_size, unit="B", unit_scale=True, unit_divisor=block_size, leave=False) as bar:
            return do_upload(bar)
    else:
        return do_upload()

def upload_asset(filename, dest=None, project=None, task=None, progress=True):
    """
    Call WebODM API endpoint to upload an asset file

    Parameters
    ----------
    filename: str
        asset filename to upload (can include subdir)
    dest: str
        asset filename and optional path to upload to,
        if omitted or contains a path only,
        will use the source filename
    project: int
        project ID
    task: str
        task ID
    progress: bool
        Show progress bar

    Returns
    -------
    object
        http response object
    """
    #Use the default selections unless arg passed
    project, task = get_selection(project, task)

    #Split path and filename in dest
    destpath = ""
    destfile = ""
    #Use provided dest path & filename
    if dest:
        destpath, destfile = os.path.split(dest)
    #Use the filename from the source path
    if not len(destfile):
        path, fn = os.path.split(filename)
        destfile = fn
    return upload(f'/projects/{project}/tasks/{task}/assets/{destpath}', filename, destfile, progress=progress)

def upload_image(filename, project, task, progress=True):
    """
    Call WebODM API endpoint to upload a source image file

    Parameters
    ----------
    filename: str
        image filename to upload
    project: int
        project ID
    task: str
        task ID
    progress: bool
        Show progress bar

    Returns
    -------
    object
        http response object
    """
    #Use the default selections unless arg passed
    project, task = get_selection(project, task)

    return upload(f'/projects/{project}/tasks/{task}/upload/', filename, progress=progress)


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

def load_projects_and_tasks(cache=project_dir):
    #Get user projects and task info from  public API
    user = os.getenv('JUPYTERHUB_USER', '')
    url = auth.settings["api_audience"] + "/plugins/asdc/usertasks?email=" + user
    try:
        response = requests.get(url, timeout=10)
        jsondata = response.json()
        #Save to ./projects
        #os.makedirs(cache, exist_ok=True)
        #with open(os.path.join(cache, 'projects.json'), 'w') as outfile:
        #    json.dump(jsondata, outfile)
        return jsondata
    except (Exception) as e:
        print("Failed to load user projects from api", e)
        return None

def create_links(src='/mnt/project', dest=project_dir):
    """
    Create symlinks with nicer names for mounted projects and tasks

    Assumes by defailt projects are mounted at /mnt/project/PID/tasks/TID,
    will create project folder in home dir with links using project
    names and task names
    """

    #1) Get the mounted projects list
    if not os.path.exists(src): return
    prjfolders = [ f.path for f in os.scandir(src) if f.is_dir() ]

    audience = auth.settings["api_audience"]
    if auth.access_token:
        #Can use authenticated API for each mounted project
        jsondata = None
    else:
        #Use the public API, requires valid username, returns all projects
        jsondata = load_projects_and_tasks(dest)
        if not jsondata:
            return

    #2) Iterate projects....
    for pf in prjfolders:
        ppath = Path(pf)
        PID = ppath.name

        #Use provided project/task data or call the API
        if jsondata:
            data = jsondata[PID]
        else:
            #Use authenticated endpoint
            response = call_api(f"{audience}/plugins/asdc/projects/{PID}/gettasks")
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

def get_tasks():
    global selected, tasks
    tasks = list(filter(None, re.split('[, ]+', os.getenv("ASDC_TASKS", ""))))
    if len(tasks) and not selected["task"]:
        selected["task"] = tasks[0]
    return tasks

def get_projects():
    global selected, projects
    projects = [int(p) for p in list(filter(None, re.split('\W+', os.getenv("ASDC_PROJECTS", ""))))]
    if len(projects) and not selected["project"]:
        selected["project"] = projects[0]
    return projects

def project_tasks(filtered=True, home=project_dir):
    """
    Returns details of projects and task heirarchy passed in,
    Uses the full cached project/task data and filters by the list of passed items
    """
    global project_dict, task_dict
    tlist = get_tasks()
    plist = get_projects()
    output = []
    #fn = os.path.join(home, 'projects.json')
    #if os.path.exists(fn):
    #    print("LOAD FROM FILE", fn)
    #    with open(fn, 'r') as infile:
    #        project_dict = json.load(infile)
    #else:
    project_dict = load_projects_and_tasks(home)
    if not project_dict:
        return None

    for p in project_dict:
        sel_p = int(p) in plist
        if not filtered or sel_p:
            output += [project_dict[p]]
            otasks = []
            for t in project_dict[p]["tasks"]:
                sel_t = t["id"] in tlist
                if not filtered or sel_t:
                    otasks += [t]
                    if not filtered:
                        otasks[-1]["selected"] = sel_t
                #Save in task_dict too
                task_dict[t["id"]] = t

            output[-1]["id"] = int(p)
            if not filtered:
                output[-1]["selected"] = sel_p
            output[-1]["tasks"] = otasks
    return output


def selection_info():
    global selected
    baseurl = settings['api_audience'] 
    if selected['project']:
        print(f"{baseurl}/projects/{selected['project']}/")
        if selected['task']:
            print(f"{baseurl}/projects/{selected['project']}/tasks/{selected['task']}")

def run_all_button():
    #Run-all below button, requires ipylab
    try:
        from ipylab import JupyterFrontEnd
        import ipywidgets as widgets
        app = JupyterFrontEnd()
        def run_all(ev):
            app.commands.execute('notebook:run-all-below')

        button = widgets.Button(description="Run all below", icon='play')
        button.on_click(run_all)
        return button
    except:
        #Nonessential feature, ignore errors
        return None

def get_task_project_options(filtered=False):
    pdata = project_tasks(filtered=filtered)
    if not pdata:
        return None, None, None, None
    pselections = []
    tselections = {}
    #If no initial selection, just use any active saved selection
    global selected
    init_p, init_t = get_selection()
    for p in pdata:
        pselections += [(str(p["id"]) + ": " + p["name"], p["id"])]
        if not init_p and (filtered or p["selected"]):
            init_p = p["id"]
        tselections[p["id"]] = []
        for t in p["tasks"]:
            tselections[p["id"]] += [("Task #" + t["id"] if t["name"] is None else t["name"] ,  t["id"])]
            if not init_t and (filtered or t["selected"]):
                init_t = t["id"]
                init_p = p["id"] #Ensure matching project selected too

    #Ensure any passed selections are valid (found in lists)
    found_p = False
    found_t = False
    for p in pselections:
        if not found_t:
            for t in tselections[p[1]]:
                if t[1] == init_t:
                    found_t = True
                    break
        if p[1] == init_p:
            found_p = True
            break
    if not found_p:
        print("Project not found: ", init_p)
        init_p = None
    if not found_t:
        print("Task not found: ", init_t)
        init_t = None

    return pselections, tselections, init_p, init_t

def project_select(filtered=False):
    """
    Display project selection widget only
    """
    if not auth.is_notebook():
        return
    import ipywidgets as widgets
    from IPython.display import display

    #Project selection widget
    pselections, tselections, init_p, init_t = get_task_project_options(filtered)
    if not pselections: return

    def select_project(project):
        global selected
        selected["project"] = projectW.value
        if project:
            baseurl = settings['api_audience'] 
            print(f"{baseurl}/projects/{selected['project']}/")

    projectW = widgets.Dropdown(options=pselections, value=init_p)
    init = pselections[0][1]
    if projectW.value:
        init = projectW.value
    i = widgets.interactive(select_project, project=projectW)
    #Run-all below button, requires ipylab
    button = run_all_button()
    if button:
        display(i, button)
    else:
        display(i)

def task_select(filtered=False):
    """
    Display project and task selection widgets
    """
    if not auth.is_notebook():
        return
    import ipywidgets as widgets
    from IPython.display import display

    #Project/task selection widget
    pselections, tselections, init_p, init_t = get_task_project_options(filtered)
    if not pselections: return

    def select_task(task):
        global selected
        #print(projectW.value, task)
        selected = {"project": projectW.value, "task" : task} # Active selections
        selection_info()

    def select_project(project):
        if project:
            taskW.options = tselections[project]

    projectW = widgets.Dropdown(options=pselections, value=init_p)
    init = pselections[0][1]
    if projectW.value:
        init = projectW.value
    taskW = widgets.Dropdown(options=tselections[init], value=init_t)
    j = widgets.interactive(select_task, task=taskW)
    i = widgets.interactive(select_project, project=projectW)
    #Run-all below button, requires ipylab
    button = run_all_button()
    if button:
        display(i, j, button)
    else:
        display(i, j)

# Active selections
selected = {"project": None, "task" : None}
tasks = get_tasks()
projects = get_projects()
task_dict = {}
project_dict = {}

def get_selection(project=None, task=None):
    """
    Get first selected project/task
    If none selected, raise exception to stop execution

    (If project or task are passed these will override selections)
    """
    global selected, projects, tasks
    init_p = selected['project']
    init_t = selected['task']
    #Use params instead if provided
    #(used from other functions with optional project/task params)
    if project is not None: init_p = project
    if task is not None: init_t = task
    #Use the first selection passed in env, or interactively select if none
    if not init_p or not init_t:
        raise(Exception("Please select a task to continue..."))

    #Return the first selection
    return init_p, init_t

def new_task(name, project=None, options=None):
    """
    Create a new task, "partial" enabled to allow later upload of images
    This is suited for creating a task that will use ODM to process a set of input images
    For pre-processed data, use the import_task() function instead.

    Parameters
    ----------
    name: str
        Name of the new task
    project: int
        Proejct id, if omitted will use current selection
    options: dict
        ODM processing options to set on the task

    eg:
    #Create a new task and add an orthophoto image
    task_id = new_task("Processed orthophoto")
    asdc.upload_asset("myfile.tif", dest="odm_orthophoto/odm_orthophoto.tif", task=task_id)
    """

    #Use the default selections unless arg passed
    project, task = get_selection(project)

    # https://github.com/localdevices/odk2odm/blob/main/odk2odm/odm_requests.py
    if options is None:
        options = {
            "auto-boundary": True,
            "dsm": True
        }
    # convert into list with "name" / "value" dictionaries, suitable for ODM
    options_list = [{"name": k, "value": v} for k, v in options.items()]
    data = {
        "partial": True,
        "name": name,
        "options": options_list
    }

    url = f"/projects/{project}/tasks/"
    res = call_api(url, data=data)
    if not res.ok:
        print("Error response:", res, url)
        return None
    task = res.json()
    return res.json()["id"]

def import_task(name, path=None, dest=None, project=None):
    """
    Creates a new task using the import API
    Files in "path" are zipped before being uploaded to the new task
    
    Parameters
    ==========
    name: str
        Name of the new task
    path: str/list
        if path=None, an empty files.json will be created and sent
        if path is a directory the entire directory will be sent
        if path is a single file, just this file will be sent
    """
    #Using the default selections
    project, _ = get_selection(project)
    if path is None:
        path = 'files.json'
        with open(path, 'w') as f:
            f.write('{"custom_assets" : []}')

    #Zip the files
    outfn = "/tmp/task.zip"
    if os.path.exists(outfn):
        os.remove(outfn)
    if os.path.isdir(path):
        #We could use os.walk with zipfile below, but this is easier
        zfile = shutil.make_archive('/tmp/task', 'zip', base_dir = path)
    else:
        with zipfile.ZipFile(outfn, "w" ) as zfile:
            if isinstance(path, str):
                path = [path]

            for f in path:
                if dest:
                    zfile.write(f, os.path.join(dest, os.path.basename(path)), zipfile.ZIP_DEFLATED)
                else:
                    zfile.write(f, compress_type=zipfile.ZIP_DEFLATED)

    #NOTE: Importing custom assets in zip will not add entries in files.json
    # until fixed, better to add them to the task with upload_asset
    
    url = f"/projects/{project}/tasks/import"
    res = upload(url, outfn, name=name)
    if not res.ok:
        print("Error response:", res, url)

    task = res.json()
    return task["id"]


