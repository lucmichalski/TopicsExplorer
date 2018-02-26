#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, QThread

import lzma
import pickle
import time
import re
import logging
from lxml import etree
from bokeh.plotting import figure
from bokeh.models import CustomJS, ColumnDataSource, HoverTool
from bokeh.models.widgets import Dropdown
from bokeh.layouts import column
import lda
from threading import Thread
import queue

from flask import Flask, request, render_template, Response, stream_with_context
import pandas as pd
import time
from bokeh.plotting import output_file, save
from bokeh.embed import components
from dariah_topics import preprocessing
from dariah_topics import postprocessing
from dariah_topics import visualization
import tempfile
import shutil
import numpy as np
from werkzeug.utils import secure_filename


PORT = 5000
ROOT_URL = 'http://localhost:{}'.format(PORT)

class FlaskThread(QThread):
    def __init__(self, application):
        QThread.__init__(self)
        self.application = application

    def __del__(self):
        self.wait()

    def run(self):
        self.application.run(port=PORT)


def ProvideGui(application):
    qtapp = QApplication(sys.argv)

    webapp = FlaskThread(application)
    webapp.start()

    qtapp.aboutToQuit.connect(webapp.terminate)

    webview = QWebEngineView()
    webview.resize(1200, 660)
    webview.setWindowTitle('Topics Explorer')
    webview.setWindowIcon(QIcon(str(Path('static', 'img', 'page_icon.png'))))

    webview.load(QUrl(ROOT_URL))
    webview.show()

    return qtapp.exec_()


if __name__ == '__main__':
    from webapp import app
    sys.exit(ProvideGui(app))
