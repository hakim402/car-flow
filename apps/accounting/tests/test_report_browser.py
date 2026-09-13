"""Opt-in, isolated browser QA: REPORT_BROWSER_TESTS=1 pytest .../test_report_browser.py.

Runs against Django's test server/database inside Docker, never customer records.
"""
import os
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounting.reporting import REPORTS
from apps.accounting.workspace_views import report_url
from apps.core.testing import SaleFactory, UserFactory


@skipUnless(os.environ.get("REPORT_BROWSER_TESTS") == "1", "Opt-in Docker browser QA")
class ReportBrowserTests(StaticLiveServerTestCase):
    def test_responsive_business_activity_report(self):
        from playwright.sync_api import sync_playwright
        user = UserFactory()
        user.roles.add(Role.objects.get(key="org_admin"))
        for _ in range(22):
            SaleFactory(company=user.company, agreed_amount=Decimal("12345.67"), status="completed")
        client = Client()
        client.force_login(user)
        output = Path(os.environ.get("REPORT_QA_OUTPUT_DIR", "/tmp/amoxruns-report-qa"))
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium-headless-shell", args=["--disable-dev-shm-usage"])
            try:
                for language in ("en", "prs", "ps"):
                    context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
                    # Authentication belongs to this isolated test user/session.
                    context.add_cookies([
                        {"name": settings.SESSION_COOKIE_NAME, "value": client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url},
                        {"name": settings.LANGUAGE_COOKIE_NAME, "value": language, "url": self.live_server_url},
                    ])
                    context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.live_server_url) else route.abort())
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    for theme in ("light", "dark"):
                        for width in (1440, 900, 390):
                            page.set_viewport_size({"width": width, "height": 1000})
                            for key in REPORTS:
                                response = page.goto(self.live_server_url + report_url(key))
                                self.assertEqual(response.status, 200)
                                page.wait_for_load_state("load")
                                if page.locator("html").evaluate("e => e.classList.contains('dark')") != (theme == "dark"):
                                    page.locator("#themeBtn").click()
                                self.assertEqual(page.locator("html").get_attribute("dir"), "ltr" if language == "en" else "rtl")
                                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - window.innerWidth"), 1, (language, theme, width, key))
                                self.assertNotEqual(page.locator(".report-workspace").evaluate("e => getComputedStyle(e).getPropertyValue('--report-brand')"), "")
                                self.assertTrue(page.locator(".workspace-hero.report-hero").is_visible())
                                self.assertEqual(page.locator("text=Browse reports").count(), 0)
                                self.assertEqual(page.locator("text=Report center").count(), 0)
                                if key == "activity":
                                    self.assertEqual(page.locator(".report-summary-analytics").count(), 0)
                                    self.assertEqual(page.locator("text=Export report").count(), 0)
                                    self.assertEqual(page.locator("text=Share snapshot").count(), 0)
                                    self.assertEqual(page.locator("text=Delivery history").count(), 0)
                                    self.assertEqual(page.locator(".report-activity-board").count(), 0)
                                    self.assertEqual(page.locator(".report-mobile-records").is_visible(), width < 768)
                                    page.screenshot(path=str(output / f"{language}-{theme}-{width}-activity.png"), full_page=True)
                            self.assertFalse(errors, errors)
                    context.close()
            finally:
                browser.close()
