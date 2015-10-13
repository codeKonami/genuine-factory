from fabric.api import env, hosts, run, local, put, get, task
from fabric.contrib.files import exists
from fabric.utils import abort
from fabric.context_managers import cd, settings, hide
from termcolor import colored as coloured
from bitbucket.bitbucket import Bitbucket
import json
import os.path
import re

env.user = "root"

def load_conf():
    '''
    This function loads and verifies all the configurations
    '''
    global servers
    global passwords
    global VAULT_URL

    VAULT_URL = os.environ.get('VAULT_URL')
    if not VAULT_URL:
        abort('You need to define a VAULT_URL like so \n export VAULT_URL="127.0.0.1"')

    global app_name
    if(os.path.isfile('genuine.json')):
        with open('genuine.json') as data_file:
            data = json.load(data_file)
            app_name = data['app_name']
            print('Configuration found for project : %s' % (app_name))
    else:
        abort('No genuine.json config file found!')
    with settings(hide('warnings', 'running', 'stdout', 'stderr'), host_string=VAULT_URL):
        result = run("vault read -format=json /secret/servers | jq -c -M .data")
        data = json.loads(result)
        servers = data['servers']
        result = run("vault read -format=json /secret/passwords | jq -c -M .data")
        data = json.loads(result)
        passwords = data['passwords']


def repo_exist():
    bb = Bitbucket(passwords['bitbucket']['username'], passwords['bitbucket']['password'])
    success, repositories = bb.repository.all(owner=passwords['bitbucket']['team'])
    for repo in sorted(repositories):
        if repo['name'] == app_name:
            return True

    return False

@task
def construct():
    '''
    This function will create the repo and generate the staging server
    '''
    load_conf()
    if repo_exist():
        abort("The repo %s exists already." % (app_name))
    print ("Creating project %s on Bitbucket..." % (app_name))
    bb = Bitbucket(passwords['bitbucket']['username'], passwords['bitbucket']['password'])
    success, result = bb.repository.create(app_name, repo_slug=app_name, owner=passwords['bitbucket']['team'])

    if success:
        print ("Project created.")
    else:
        abort("An error occured. Try again!")

    print ("Preparing the local repo and connecting remotely...")
    local("git init")
    local("git remote add origin git@bitbucket.org:%s/%s.git" % (passwords['bitbucket']['team'], app_name))
    local("git add .")
    local("git commit -m 'Initial commit from Fabric'")
    local("git tag -a 1.0.0 -m 'First version'")
    local("git push -u origin master")
    local("git push --tags")
    local("git checkout -b develop master")
    local("git push origin develop")
    print ("Your repo is ready!")

    print ("Installation of the repo on the staging platform...")
    with settings(warn_only=True, host_string=servers['staging']['ip']):
        with cd("/home/"):
            run("mkdir %s" % (app_name))
        with cd("/home/%s" % (app_name)):
            run("mkdir logs")
            run("touch logs/access.log")
            run("touch logs/error.log")
            run("git clone git@bitbucket.org:%s/%s.git public" % (passwords['bitbucket']['team'], app_name))
        with cd("/home/%s/public" % (app_name)):
            run("""for i in {3200..3000}; do netstat -ano|grep $i|grep LISTEN > /tmp/test.txt && echo \ || echo $i > /tmp/port; done""")
            run("""echo "export NODE_ENV_%s_port=""$(cat /tmp/port)" >> /etc/environment""" % (app_name))
            port = run("cat /tmp/port")
            run("git checkout -b develop origin/develop")
            run("npm install --production")
            run("gulp sass")
            run("gulp js")
            print ("Launching")

        # Nginx Server Blocks
        run("echo '%s' >> /etc/nginx/sites-available/%s" % (create_nginx_server_blocks(port),app_name))
        run("ln -s /etc/nginx/sites-available/%s /etc/nginx/sites-enabled/%s" % (app_name,app_name))
        run("service nginx restart")
        with cd("/home/%s/public" % (app_name)):
            run("NODE_ENV_%s_port=%s forever start --uid '%s' app.js" % (app_name, port, app_name))
        print ("You should be able to see your website here : http://%s.%s" % (app_name, servers['staging']['dns']))

@task
def destroy():
    '''
    This function will destroy the repo and the presence of the project on the staging and production server
    '''
    load_conf()
    with settings(warn_only=True, host_string=servers['staging']['ip']):
        run("forever stop %s" % (app_name))
        run("rm -Rf /root/.forever/%s.log" % (app_name))
        run("""sed -i '/_%s_/d' /etc/environment""" % (app_name))
        run("rm -Rf /home/%s" % (app_name))
        run("rm /etc/nginx/sites-available/%s" % (app_name))
        run("rm /etc/nginx/sites-enabled/%s" % (app_name))
        run("service nginx restart")
        bb = Bitbucket(passwords['bitbucket']['username'], passwords['bitbucket']['password'])
        success, result = bb.repository.delete(repo_slug=app_name, owner=passwords['bitbucket']['team'])
        run("rm -Rf .git")

@task
def deploy(environment = 'staging'):
    '''
    This function will deploy on the platform wanted (staging, prod, all)
    '''
    # TODO It would be good to test if the local change have been commited and pushed
    if(environment == 'staging'):
        _deploy()
    elif(environment == 'prod' or environment == 'production'):
        _deploy('production')
    elif(environment == 'all'):
        _deploy()
        _deploy('production')
    else:
        abort('The platform %s does not exist' % (environment))

def _deploy(environment = 'staging'):
    load_conf()
    print('Rollback on %s ...' % (environment))
    with settings(warn_only=True, host_string=servers[environment]['ip']):
        with cd("/home/%s/public" % (app_name)):
            run("git stash")
            run("git pull")
            run("npm install --production")
            run("gulp sass")
            run("gulp js")
            run("forever restart %s" % (app_name))

@task
def rollback(revert = '1', environment = 'staging'):
    '''
    This function will rollback on the platform wanted (staging, prod, all) by default only one commit on staging will be rollback
    '''
    rollback_type = "commit"
    if re.match("^(\d+\.)(\d+\.)(\d+)$", revert):
        print ('Rollback to the version number %s' % (revert))
        rollback_type = "version"
    elif re.match("^[0-9a-f]{5,40}$", revert):
        print ('Rollback to the commit number %s' % (revert))
        rollback_type = "sha"
    elif re.match("^[0-9]+$", revert):
        print ('Rollback %s commit(s)' % (revert))
    else:
        abort('To rollback you need to indicate a version number, a commit SHA or a number of commits to rollback')

    if(environment == 'staging'):
        _rollback(rollback_type, revert)
    elif(environment == 'prod' or environment == 'production'):
        _rollback(rollback_type, revert, 'production')
    elif(environment == 'all'):
        _rollback(rollback_type, revert)
        _rollback(rollback_type, revert, 'production')
    else:
        abort('The platform %s does not exist' % (environment))

def _rollback(rollback_type = "commit", revert = "1", environment = 'staging'):
    load_conf()
    print('Rollback on %s ...' % (environment))
    with settings(warn_only=True, host_string=servers[environment]['ip']):
        with cd("/home/%s/public" % (app_name)):
            run("git stash")
            if(rollback_type == "commit"):
                run("git reset --hard HEAD~%s" % (revert))
            elif(rollback_type == "version" or rollback_type == "sha"):
                run("git reset --hard %s" % (revert))
            run("npm install --production")
            run("gulp sass")
            run("gulp js")
            run("forever restart %s" % (app_name))

def create_nginx_server_blocks(port = 3000):

	return """
    server {
                listen 0.0.0.0:80;
                server_name %(0)s.%(1)s;
                access_log /home/%(0)s/logs/access.log;
                error_log /home/%(0)s/logs/error.log;

                location / {
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header HOST $http_host;
                    proxy_set_header X-NginX-Proxy true;
                    proxy_pass http://127.0.0.1:%(2)s;
                    proxy_redirect off;
                }
            }
	""" % {"0" : app_name, "1" : servers['staging']['dns'], "2" : port}
