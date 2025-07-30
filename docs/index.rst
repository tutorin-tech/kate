Kate
====

Kate is a web-based terminal emulator. The project is based on completely
reworked source code of `Ajaxterm
<https://github.com/antonylesuisse/qweb/tree/master/ajaxterm>`_. It understands
only Linux console escape and control sequences so far. The main goal of the
project is to be used in `OpenStack <https://openstack.org>`_ one day.

Installation
------------

Kate consists of two parts: a client and a server. The following sections
describe how to install Kate automatically and manually. You will need ``npm``
to get the client package or build it from the source code. If you don't have
``npm`` installed, have a look at `nvm <https://github.com/creationix/nvm>`_.

**Automatic installation**

The Kate client is listed in `npm search
<https://www.npmjs.com/package/kate-client>`_ and can be installed with
``npm``. For example::

    npm install kate-client

The ``node_modules`` directory will be created inside the current working
directory.

The Kate server is listed in `PyPI <http://pypi.python.org/pypi/kate>`_ and
can be installed with ``pip`` or ``easy_install``.

First, (*optionally*) prepare a virtualenv::

    virtualenv -p python3 kate-env
    . kate-env/bin/activate

Then, install the server::

    pip install kate

Finally, go to the directory where you executed ``npm install kate-client`` and
run ``server.py``. The server tries to use the
``node_modules/kate-client/static`` and  ``node_modules/kate-client/templates``
directories by default. Also you can explicitly specify which directories
should be used through the ``--static-path`` and ``--templates-path``
parameters.

**Manual installation**

First, get the Kate source code::

    git clone https://github.com/tutorin-tech/kate.git
    cd kate

Then, build the client::

    npm install
    npm run start

Next, (*optionally*) prepare a virtualenv::

    virtualenv -p python3 kate-env
    . kate-env/bin/activate

After that, intall the server::

    python setup.py install

Finally, run the server::

    server.py --static-path=static --templates-path=templates

or

.. parsed-literal::

    ./bin/server.py --static-path=static --templates-path=templates

As previously mentioned in *Automatic installation*, the server tries to use
the ``node_modules/kate-client/static`` and
``node_modules/kate-client/templates`` directories by default. In this case
they don't exist, so you have to explicitly specify which directories should be
used through the ``--static-path`` and ``--templates-path`` parameters.

**Prerequisites**

Kate uses

* `SSH <https://en.wikipedia.org/wiki/Secure_Shell>`_ to remotely login into a 
  system. You need to ensure, that ssh daemon is running, before you'll start
  a kate server.

* `Tornado <http://tornadoweb.org>`_ to create a WebSocket server and multiplex
  input/output in a platform-independent way
* `PyYAML <http://pyyaml.org>`_ to store escape and control sequences in a YAML
  file.

**Platforms**

Theoretically Kate is platform-independent software (generally because of using
Tornado), but practically the quality of its work may vary from platform to
platform.

Licensing
---------

Kate is available under the `Apache License, Version 2.0
<http://www.apache.org/licenses/LICENSE-2.0.html>`_.
