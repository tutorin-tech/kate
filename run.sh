#!/bin/sh

env PYTHONPATH=$(pwd) ./bin/server.py --static-path=kate/static --templates-path=kate/templates
