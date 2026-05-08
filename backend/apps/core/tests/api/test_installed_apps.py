"""Regression guard: apps.sales and apps.financials are in INSTALLED_APPS.

drf-spectacular's tag discovery walks INSTALLED_APPS, not urls.py includes.
Without registration these apps' tags appear ungrouped in the schema.
"""

from django.apps import apps


def test_sales_app_registered():
    config = apps.get_app_config("sales")
    assert config is not None
    assert config.label == "sales"


def test_financials_app_registered():
    config = apps.get_app_config("financials")
    assert config is not None
    assert config.label == "financials"
