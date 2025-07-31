#!/bin/sh

env PYTHONPATH=$(pwd) ./bin/server.py --static-path=kate/static --templates-path=templates
