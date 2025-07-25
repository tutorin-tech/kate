#!/bin/sh

env PYTHONPATH=$(pwd) ./bin/server.py --static-path=static --templates-path=templates
