#!/usr/bin/env python3
"""Rented cloud phone (Appium) config for job-apply automation.

Providers: lambdatest (TestMu AI), browserstack, sauce, generic Appium hub.

Env (see CLOUD_MOBILE.md / cloud_device.env.example):
  APPLY_BROWSER=cloud_mobile
  CLOUD_DEVICE_PROVIDER=lambdatest|browserstack|sauce|generic
  CLOUD_DEVICE_NAME=Galaxy S26
  CLOUD_PLATFORM_VERSION=16
  CLOUD_BROWSER=Chrome
  LT_USERNAME / LT_ACCESS_KEY          (LambdaTest)
  BROWSERSTACK_USERNAME / BROWSERSTACK_ACCESS_KEY
  SAUCE_USERNAME / SAUCE_ACCESS_KEY
  APPIUM_HUB_URL                       (optional full hub override)
  CLOUD_BUILD_NAME / CLOUD_SESSION_NAME
  CLOUD_IDLE_TIMEOUT_SEC               (default 300)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class CloudDeviceConfig:
    provider: str
    hub_url: str
    capabilities: dict[str, Any]
    device_name: str
    browser: str


def provider_name() -> str:
    return _env("CLOUD_DEVICE_PROVIDER", "lambdatest").lower()


def device_name() -> str:
    return _env("CLOUD_DEVICE_NAME", "Galaxy S26")


def platform_version() -> str:
    return _env("CLOUD_PLATFORM_VERSION", "")


def browser_name() -> str:
    return _env("CLOUD_BROWSER", "Chrome")


def build_name() -> str:
    return _env("CLOUD_BUILD_NAME", "karlsruhe-job-apply")


def session_name() -> str:
    return _env("CLOUD_SESSION_NAME", "complete_apply_cloud_mobile")


def idle_timeout_sec() -> int:
    try:
        return int(_env("CLOUD_IDLE_TIMEOUT_SEC", "300") or "300")
    except ValueError:
        return 300


def is_real_mobile() -> bool:
    """Default True; set CLOUD_REAL_MOBILE=0 for virtual/emulator (cheaper plans)."""
    v = _env("CLOUD_REAL_MOBILE", "1").lower()
    return v not in ("0", "false", "no", "virtual", "emulator")


def is_cloud_mobile() -> bool:
    b = _env("APPLY_BROWSER", "chromium").lower()
    return b in ("cloud_mobile", "appium", "mobile_cloud", "s26", "galaxy_s26")


def _lambdatest_config() -> CloudDeviceConfig:
    user = _env("LT_USERNAME") or _env("LAMBDATEST_USERNAME")
    key = _env("LT_ACCESS_KEY") or _env("LAMBDATEST_ACCESS_KEY")
    if not user or not key:
        raise RuntimeError(
            "LambdaTest credentials missing. Set LT_USERNAME and LT_ACCESS_KEY "
            "(see cloud_device.env.example)."
        )
    hub = _env("APPIUM_HUB_URL") or (
        f"https://{quote(user, safe='')}:{quote(key, safe='')}"
        f"@mobile-hub.lambdatest.com/wd/hub"
    )
    dev = device_name()
    ver = platform_version()
    real = is_real_mobile()
    caps: dict[str, Any] = {
        "platformName": "Android",
        "browserName": browser_name(),
        "deviceName": dev,
        "isRealMobile": real,
        "build": build_name(),
        "name": session_name(),
        "console": True,
        "network": True,
        "visual": True,
        "video": True,
        "w3c": True,
        "devicelog": True,
        "idleTimeout": idle_timeout_sec(),
        # LambdaTest also accepts lt:options
        "lt:options": {
            "platformName": "Android",
            "deviceName": dev,
            "isRealMobile": real,
            "build": build_name(),
            "name": session_name(),
            "w3c": True,
            "idleTimeout": idle_timeout_sec(),
        },
    }
    if ver:
        caps["platformVersion"] = ver
        caps["lt:options"]["platformVersion"] = ver
    return CloudDeviceConfig(
        provider="lambdatest",
        hub_url=hub,
        capabilities=caps,
        device_name=dev,
        browser=browser_name(),
    )


def _browserstack_config() -> CloudDeviceConfig:
    user = _env("BROWSERSTACK_USERNAME") or _env("BS_USERNAME")
    key = _env("BROWSERSTACK_ACCESS_KEY") or _env("BS_ACCESS_KEY")
    if not user or not key:
        raise RuntimeError(
            "BrowserStack credentials missing. Set BROWSERSTACK_USERNAME and "
            "BROWSERSTACK_ACCESS_KEY (see cloud_device.env.example)."
        )
    hub = _env("APPIUM_HUB_URL") or (
        f"https://{quote(user, safe='')}:{quote(key, safe='')}"
        f"@hub-cloud.browserstack.com/wd/hub"
    )
    dev = device_name()
    ver = platform_version()
    bstack_opts: dict[str, Any] = {
        "deviceName": dev,
        "realMobile": "true",
        "projectName": "karlsruhe-job-apply",
        "buildName": build_name(),
        "sessionName": session_name(),
        "debug": "true",
        "networkLogs": "true",
        "appiumVersion": _env("CLOUD_APPIUM_VERSION", "2.6.0") or "2.6.0",
        "idleTimeout": idle_timeout_sec(),
    }
    if ver:
        bstack_opts["osVersion"] = ver
    caps: dict[str, Any] = {
        "platformName": "Android",
        "browserName": browser_name(),
        "bstack:options": bstack_opts,
    }
    return CloudDeviceConfig(
        provider="browserstack",
        hub_url=hub,
        capabilities=caps,
        device_name=dev,
        browser=browser_name(),
    )


def _sauce_config() -> CloudDeviceConfig:
    user = _env("SAUCE_USERNAME")
    key = _env("SAUCE_ACCESS_KEY")
    if not user or not key:
        raise RuntimeError(
            "Sauce Labs credentials missing. Set SAUCE_USERNAME and SAUCE_ACCESS_KEY."
        )
    region = _env("SAUCE_REGION", "us-west-1") or "us-west-1"
    hub = _env("APPIUM_HUB_URL") or (
        f"https://{quote(user, safe='')}:{quote(key, safe='')}"
        f"@ondemand.{region}.saucelabs.com:443/wd/hub"
    )
    dev = device_name()
    ver = platform_version()
    options: dict[str, Any] = {
        "deviceName": dev,
        "platformName": "Android",
        "browserName": browser_name(),
        "appium:automationName": "UiAutomator2",
        "sauce:options": {
            "name": session_name(),
            "build": build_name(),
            "appiumVersion": _env("CLOUD_APPIUM_VERSION", "latest") or "latest",
            "idleTimeout": idle_timeout_sec(),
        },
    }
    if ver:
        options["appium:platformVersion"] = ver
        options["platformVersion"] = ver
    return CloudDeviceConfig(
        provider="sauce",
        hub_url=hub,
        capabilities=options,
        device_name=dev,
        browser=browser_name(),
    )


def _generic_config() -> CloudDeviceConfig:
    hub = _env("APPIUM_HUB_URL")
    if not hub:
        raise RuntimeError(
            "Generic provider needs APPIUM_HUB_URL "
            "(e.g. http://127.0.0.1:4723/wd/hub)."
        )
    dev = device_name()
    ver = platform_version()
    caps: dict[str, Any] = {
        "platformName": "Android",
        "browserName": browser_name(),
        "appium:deviceName": dev,
        "appium:automationName": _env("CLOUD_AUTOMATION_NAME", "UiAutomator2")
        or "UiAutomator2",
    }
    if ver:
        caps["appium:platformVersion"] = ver
    return CloudDeviceConfig(
        provider="generic",
        hub_url=hub,
        capabilities=caps,
        device_name=dev,
        browser=browser_name(),
    )


def load_config() -> CloudDeviceConfig:
    p = provider_name()
    if p in ("lambdatest", "lt", "testmu", "testmuai"):
        return _lambdatest_config()
    if p in ("browserstack", "bs"):
        return _browserstack_config()
    if p in ("sauce", "saucelabs"):
        return _sauce_config()
    if p in ("generic", "local", "appium"):
        return _generic_config()
    raise RuntimeError(
        f"Unknown CLOUD_DEVICE_PROVIDER={p!r}. "
        "Use lambdatest | browserstack | sauce | generic."
    )


def redacted_hub(hub: str) -> str:
    """Hub URL safe for logs (strip user:pass)."""
    if "@" not in hub:
        return hub
    try:
        scheme, rest = hub.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return f"{scheme}://***@{host}"
    except Exception:
        return hub.split("@")[-1]
