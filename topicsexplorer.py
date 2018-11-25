#!/usr/bin/env python3

import argparse
import sys
import webbrowser

import application


NAME = "DARIAH Topics Explorer"
DESCRIPTION = "Explore your own text collection with a topic model – without prior knowledge."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog=NAME,
                                     description=DESCRIPTION)
    parser.add_argument("--browser",
                        action="store_true",
                        help="Use this parameter to open the UI in your default web browser.")
    parser.add_argument("--frozen",
                        action="store_true",
                        help="Simulate a frozen application.")

    args = parser.parse_args()

    if args.browser:
        webbrowser.open("http://localhost:5000/")
        application.views.web.run()
    elif getattr(sys, "frozen", False) or args.frozen:
        application.views.web.run()
    else:
        application.gui.run()