"""Celery application for AUTOMEX CarFlow.

Imported by config/__init__.py so `celery -A config worker` picks it up.
Task modules are autodiscovered from every installed app's tasks.py.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("automex_carflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
