import tornado.ioloop
import tornado.web
import tornado.httpclient
import tornado.httputil
import sys
import os
from asdc import custom

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


py_base = """
# + [markdown] inputHidden=false outputHidden=false
# # Loading a data set from ASDC WebODM
#
# This notebook / script will load a specific task dataset
#

# + inputHidden=false outputHidden=false
import asdc

await asdc.auth.connect(mode='iframe')

project = '{PID}'
task = '{TID}'
filename = '{ASSET}'
asdc.download(project, task, filename)

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
    <a href="/user-redirect/lab/tree/{FN}">(Output here)</a>
    </p>
</body>

</html>
"""

class ImportHandler(tornado.web.RequestHandler):
    def get(self):
        #Write a python module to import the selected task
        project = self.get_argument('project')
        task = self.get_argument('task')
        asset = self.get_argument('asset', 'orthophoto.tif')
        redirect = self.get_argument('redirect', 'yes')
        filename = 'task_{0}.py'.format(task)

        # Write the python script / notebook
        from pathlib import Path
        with open(str(Path.home() / filename), 'w') as f:
            f.write(py_base.format(PID=project, TID=task, ASSET=asset))

        script = ""
        if redirect == 'yes':
            script = 'window.location.href="/user-redirect/lab/tree/{FN}"'.format(FN=filename)

        self.write(import_doc.format(FN=filename, script=script))

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
        }

        // post message back to parent window
        sendMessageToParent(window, objMsg);

        msg.innerHTML = msgHTML + '<p>Close this tab/popup and start again</p>'

        console.log('done');

        window.close();
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
        (r"/import", ImportHandler),
        (r"/callback", CallbackHandler)
    ])
    app.listen(sys.argv[1])
    tornado.ioloop.IOLoop.current().start()


