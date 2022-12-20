import tornado.ioloop
import tornado.web
import tornado.httpclient
import tornado.httputil
import sys
import os
import re
from slugify import slugify

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
filename = '{ASSET}'
pathlib.Path(task).mkdir(parents=True, exist_ok=True)
os.chdir(task)
asdc.download_asset(project_id, task_id, filename)

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

#prefix = os.getenv('JUPYTERHUB_SERVICE_PREFIX')
#user = os.getenv('JUPYTERHUB_USER')
#baseurl = os.getenv('JUPYTERHUB_URL')
server = os.getenv('JUPYTERHUB_SERVER_NAME', '')
#fullurl = f'{baseurl}/{prefix}'
fullurl = f'/user-redirect/'
if len(server):
    fullurl = f'/user-redirect/{server}/'

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
    """
    def get(self):
        logger.info("Handling redirect")
        projects = [int(p) for p in list(filter(None, re.split('\W+', self.get_argument('projects'))))]
        tasks = list(filter(None, re.split('[, ]+', self.get_argument('tasks'))))
        redirect = self.get_argument('path')
        print(projects,tasks,redirect)

        utils.write_inputs(projects=projects, tasks=tasks)

        return self.redirect(f"{fullurl}lab/tree/{redirect}")

class ImportHandler(tornado.web.RequestHandler):
    def get(self):
        #Write a python module to import the selected task
        logger.info("Handling import")
        project = self.get_argument('project')
        task = self.get_argument('task')
        asset = self.get_argument('asset', 'orthophoto.tif')
        redirect = self.get_argument('redirect', 'yes')
        filename = 'task_{0}.py'.format(task)

        # Write the python script / notebook
        with open(str(Path.home() / filename), 'w') as f:
            f.write(py_base.format(PID=project, TID=task, ASSET=asset))

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
                    print("Unexpected response: ", data)
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
            tpath = "/mnt/project/{PID}/task/TID"
            lnpath = os.path.join(phome, str(PID))
            os.makedirs(lnpath, exist_ok=True)
            lnpath = os.path.join(lnpath, TID)
            os.symlink(tpath, lnpath)
            return self.redirect(f"{fullurl}lab/tree/projects/{PID}/{TID}")

# Following page HTML and Javascript from ipyauth
# https://gitlab.com/oscar6echo/ipyauth
ipyauth_doc = """
<!DOCTYPE html>
<html lang="en">

<!--
(Code pulled from ipyauth, originals in these files):
https://gitlab.com/oscar6echo/ipyauth/-/tree/master/ipyauth/ipyauth_callback/templates/index.html
https://gitlab.com/oscar6echo/ipyauth/-/blob/master/ipyauth/ipyauth_callback/templates/assets/util.js
https://gitlab.com/oscar6echo/ipyauth/-/blob/master/ipyauth/ipyauth_callback/templates/assets/main.js

The MIT License (MIT)

Copyright (c) 2018 Olivier Borderies

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

-->
<head>
    <meta charset="utf-8" />
    <title>ipyauth Callback</title>
</head>

<body>
    <h1>OAuth2 Callback</h3>
    <div id="msg"></div>

    <script type="text/javascript">
        //-- assets/util.js
        function getDataFromCallbackUrl() {
            const url1 = window.location.href.split('#')[1];
            const url2 = window.location.href.split('?')[1];
            const url = url1 ? url1 : url2;
            const urlParams = new URLSearchParams(url);
            const data = Object.assign(
                ...Array.from(urlParams.entries()).map(([k, v]) => ({ [k]: v }))
            );
            return data;
        }

        function parseJwt(id_token) {
            const base64Url = id_token.split('.')[1];
            const base64 = base64Url.replace('-', '+').replace('_', '/');
            return JSON.parse(window.atob(base64));
        }

        function containsError(urlData) {
            let e = false;
            if ('error' in urlData) e = true;
            if ('error_description' in urlData) e = true;
            if (!('access_token' in urlData) && !('code' in urlData)) e = true;
            if (!('state' in urlData)) e = true;
            return e;
        }

        function sendMessageToParent(window, objMsg) {
            if (window.opener) {
                //console.log('window.opener: ' + window.opener);
                window.opener.postMessage(objMsg, '*');
            } else if (window.parent) {
                //console.log('window.parent: ' + window.parent);
                window.parent.postMessage(objMsg, '*');
                //if (window.parent.opener) {
                //    //console.log('window.parent.opener: ' + window.parent.opener);
                //    window.parent.opener.postMessage(objMsg, '*');
                //}
            }
        }

        //-- assets/main.js
        console.log('start callback');

        // extract urlData
        const urlData = getDataFromCallbackUrl();
        window.urlData = urlData;

        // build id_token: JWT by openid spec
        let id_token;
        if (urlData.id_token) {
            id_token = parseJwt(urlData.id_token);
            urlData.id_token = id_token;
        }
        //console.log('id_token: ' + id_token);
        //console.log('urlData: ' + urlData);

        // check if urlData means an authentication error
        var msg = document.getElementById('msg');
        var msgHTML = '';
        if (containsError(urlData)) {
            // error in authentication
            console.log('error in urlData');

            msgHTML = '<h2>Authentication failed.</h2><p>urlData:'
                      + JSON.stringify(urlData) + '</p>';

            // build message
            objMsg = Object.assign({ statusAuth: 'error' }, urlData);

            // post message back to parent window
            sendMessageToParent(window, objMsg);

            msg.innerHTML = msgHTML;

        } else {
            // no error
            console.log('No error in urlData');

            // get access_token and code
            const access_token = urlData.access_token || null;
            const code = urlData.code || null;
            //console.log('access_token: ' + access_token);
            //console.log('code: ' + code);

            msgHTML = '<h2>Authentication completed.</h2>'
            //msgHTML += `<p>The access_token is ${access_token}</p>`;
            //msgHTML += `<p>The code is ${code}</p>`;

            // build message
            objMsg = Object.assign({ statusAuth: 'ok' }, urlData);

            // post message back to parent window
            sendMessageToParent(window, objMsg);

            msg.innerHTML = msgHTML + '<p>Close this tab/popup and start again</p>'

            //Close the popup
            window.close();
        }

    </script>
</body>

</html>
"""

class CallbackHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(ipyauth_doc)

if __name__ == "__main__":
    print("Starting OAuth2 callback server", sys.argv)
    app = tornado.web.Application([
        (r"/", RootHandler),
        (r"/redirect", RedirectHandler),
        (r"/import", ImportHandler),
        (r"/browse", BrowseHandler),
        (r"/callback", CallbackHandler)
    ])
    app.listen(sys.argv[1])
    tornado.ioloop.IOLoop.current().start()


