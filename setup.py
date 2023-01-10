import setuptools

setuptools.setup(
    name="asdc",
    version='1.1.0',
    url='https://github.com/AuScalableDroneCloud/asdc-python',
    author='Owen Kaluza',
    author_email='owen.kaluza@monash.edu',
    description='ASDC Utils including OAuth2 for Jupyter/lab/hub',
    packages=setuptools.find_packages(),
    install_requires=['jupyter-server-proxy', 'pillow', 'qrcode','tqdm', 'python-dotenv', 'python-slugify', 'requests-toolbelt', 'piexif', 'pyjwt', 'browser_cookie3'],
    #entry_points={
    #    'jupyter_serverproxy_servers': [
    #        # name = packagename:function_name
    #        'asdc = asdc:setup_asdc',
    #    ]
    #},
)

