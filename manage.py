#!/usr/bin/env python
"""Django's command-line tool: runserver, migrate, createsuperuser, ..."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nopsite.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
