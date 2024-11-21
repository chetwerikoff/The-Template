from __future__ import annotations

import json
import random
from typing import Optional, Literal

import requests

from config.settings import config
from models.account import Account
from utils.utils import random_sleep, get_response

from playwright.sync_api import sync_playwright, Browser, Page, Locator, Playwright
from loguru import logger


class Ads:
    _local_api_url = "http://local.adspower.net:50325/api/v1/"

    def __init__(self, account: Account, proxy: Optional[str] = None):
        self.profile_number = account.profile_number
        if not config.is_browser_run:
            return

        if config.set_proxy:
            self.proxy = proxy
            self._set_proxy()
        self.pw: Optional[Playwright] = None
        self.browser = self._start_browser()
        self.context = self.browser.contexts[0]
        self.page = self.context.new_page()
        self._prepare_browser()

        if config.is_mobile_proxy:
            get_response(config.link_change_ip, attempts=1, return_except=False)

        if config.check_proxy:
            self._check_proxy()

    def _open_browser(self) -> str:
        """
        Открывает браузер в ADS, номер профиля берется из self.profile_number
        :return: параметры запущенного браузера
        """
        params = dict(serial_number=self.profile_number)
        url = self._local_api_url + 'browser/start'
        random_sleep(1, 2)
        try:
            data = get_response(url, params)
            return data['data']['ws']['puppeteer']
        except Exception as e:
            logger.error(f"{self.profile_number}: Ошибка при открытии браузера: {e}")
            raise e

    def _check_browser_status(self) -> Optional[str]:
        """
        Проверяет статус браузера в ADS, номер профиля берется из self.profile_number
        :return: параметры запущенного браузера
        """
        params = dict(serial_number=self.profile_number)
        url = self._local_api_url + 'browser/active'
        random_sleep(1, 2)
        try:
            data = get_response(url, params)
            if data['data']['status'] == 'Active':
                logger.info(f"{self.profile_number}: Браузер уже активен")
                return data['data']['ws']['puppeteer']
            return None
        except Exception as e:
            logger.error(
                f"{self.profile_number}: Ошибка при проверке статуса браузера (запущен ли ADS?: {e} ")
            raise e

    def _start_browser(self) -> Browser:
        """
        Запускает браузер в ADS, номер профиля берется из self.profile_number
        Делает 3 попытки прежде чем вызвать исключение.
        :return: объект Browser
        """
        for attempt in range(3):
            try:
                # Проверяем статус браузера и запускаем его, если не активен
                if not (endpoint := self._check_browser_status()):
                    logger.info(f"{self.profile_number}: Запускаем браузер")
                    random_sleep(3, 4)
                    endpoint = self._open_browser()

                # подключаемся к браузеру
                random_sleep(4, 5)
                self.pw = sync_playwright().start()
                slow_mo = random.randint(800, 1200)
                browser = self.pw.chromium.connect_over_cdp(endpoint, slow_mo=slow_mo)
                if browser.is_connected():
                    return browser
                logger.error(f"{self.profile_number}: Error не удалось запустить браузер")

            except Exception as e:
                logger.error(f"{self.profile_number}: Error не удалось запустить браузер {e}")
                self.pw.stop() if self.pw else None
                random_sleep(5, 10)

        raise Exception(f"{self.profile_number}: Error не удалось запустить браузер")

    def _prepare_browser(self) -> None:
        """
        Закрывает все страницы кроме текущей
        :return: None
        """
        try:
            for page in self.context.pages:
                if 'offscreen' in page.url:
                    continue
                if page.url != self.page.url:
                    page.close()

        except Exception as e:
            logger.error(f"{self.profile_number}: Ошибка при закрытии страниц: {e}")
            raise e

    def close_browser(self) -> None:
        """
        Останавливает браузер в ADS, номер профиля берется из self.profile_number
        :return: None
        """
        if not config.is_browser_run:
            return
        self.browser.close()
        self.pw.stop() if self.pw else None
        params = dict(serial_number=self.profile_number)
        url = self._local_api_url + 'browser/stop'
        random_sleep(1, 2)
        try:
            get_response(url, params)
        except Exception as e:
            logger.error(f"{self.profile_number} Ошибка при остановке браузера: {e}")
            raise e

    def catch_page(self, url_contains: str | list[str] = None, timeout: int = 10) -> \
            Optional[Page]:
        """
        Ищет страницу по частичному совпадению url.
        :param url_contains: текст, который ищем в url или список текстов
        :param timeout: время ожидания
        :return: страница с нужным url или None
        """
        if isinstance(url_contains, str):
            url_contains = [url_contains]

        for attempt in range(timeout):
            for page in self.context.pages:
                for url in url_contains:
                    if url in page.url:
                        return page
                    if attempt and attempt % 5 == 0:
                        self.pages_context_reload()
                    random_sleep(1, 2)

        logger.error(f"{self.profile_number} Ошибка страница не найдена: {url_contains}")
        return None

    def pages_context_reload(self) -> None:
        """
        Перезагружает контекст вкладок. Необходимо когда playwright не видит вкладку.
        :return: None
        """
        self.context.new_page()
        random_sleep(1, 2)
        for page in self.context.pages:
            if 'about:blank' in page.url:
                page.close()

    def _set_proxy(self) -> None:
        """
        Устанавливает прокси для профиля в ADS
        :return: None
        """
        try:
            ip, port, login, password = self.proxy.split(":")

            profile_id = self._get_profile_id()

            proxy_config = {
                "proxy_type": "http",
                "proxy_host": ip,
                "proxy_port": port,
                "proxy_user": login,
                "proxy_password": password,
                "proxy_soft": "other"
            }

            data = {
                "user_id": profile_id,
                "user_proxy_config": proxy_config
            }
            url = self._local_api_url + "user/update"
            response = requests.post(url, json=data, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            random_sleep(2)

        except Exception as e:
            logger.error(f"{self.profile_number} Ошибка при установке прокси: {e}")
            raise e

    def _get_profile_id(self) -> str:
        """
        Запрашивает id профиля в ADS по номеру профиля
        :return: id профиля в ADS
        """
        url = self._local_api_url + 'user/list'
        params = {"serial_number": self.profile_number}

        random_sleep(1, 2)
        try:
            data = get_response(url, params)
            return data['data']['list'][0]['user_id']
        except Exception as e:
            logger.error(f"{self.profile_number} Ошибка при получении id профиля: {e}")
            raise e

    def _check_proxy(self) -> None:
        """
        Проверяет, что прокси работает, сравнивая ip профиля и прокси, вызывает исключение, если не совпадают
        :return: None
        """
        ip, port, login, password = self.proxy.split(":")
        current_ip = self._get_ip()
        logger.error(f"{self.profile_number} Текущий ip: {current_ip}")
        if current_ip != ip:
            raise Exception("Прокси не работает")

    def _get_ip(self) -> str:
        """
        # Получает ip текущего профиля
        # :return: ip_check_browser_status
        # """
        try:
            ip = self.page.evaluate('''
                        async () => {
                            const response = await fetch('https://api.ipify.org');
                            const data = await response.text();
                            return data;
                        }
                    ''')
        except Exception:
            logger.error(f"{self.profile_number} Ошибка при получении ip")
            self.page.goto("https://api.ipify.org/?format=json")
            random_sleep(1, 2)
            ip_text = self.page.locator("//pre").inner_text()  # парсим json и возвращаем ip
            ip = json.loads(ip_text)["ip"]  # парсим json и возвращаем ip

        return ip

    def open_url(
            self,
            url: str,
            wait_until: Optional[
                Literal["commit", "domcontentloaded", "load", "networkidle"]
            ] = "load",
            locator: Optional[Locator] = None,
            timeout: int = 30,
            attempts: int = 1
    ) -> None:
        """
        Открывает страницу по url, если еще не открыта. Может ждать элемент на странице.
        :param url: ссылка на страницу, желательно в формате https://
        :param wait_until: состояние страницы, когда считается что она загрузилась. По умолчанию load.
        :param locator: элемент, который нужно дождаться на странице
        :param timeout: время ожидания в секундах
        :param attempts: количество попыток открыть страницу
        :return: None
        """
        # Переводим время ожидания в миллисекунды, если передали секунды
        if timeout < 1000:
            timeout = timeout * 1000

        # Проверяем, если передана ссылка на расширение chrome
        if not url.startswith("chrome-extension"):
            # Проверяем и добавляем https:// если необходимо
            if not (url.startswith("http://") or url.startswith("https://")):
                url = f"https://{url}"

        # Проверяем, если одна из версий URL уже открыта
        if self.page.url != url:
            for attempt in range(attempts):
                try:
                    self.page.goto(url, wait_until=wait_until, timeout=timeout)
                    break
                except Exception as e:
                    if attempt == attempts - 1:
                        raise e
                    logger.error(f"{self.profile_number}: Ошибка при открытии страницы {url}: {e}")
                    random_sleep(1, 2)

        # Если передан xpath, ждем элемент на странице заданное время
        if locator:
            locator.wait_for(state='visible', timeout=timeout)

    def click_if_exists(
            self,
            locator: Optional[Locator] = None,
            *,
            method: Optional[Literal["test_id", "role", "text"]] = None,
            value: Optional[str] = None
    ) -> None:
        """
        Кликает по элементу, если он существует, можно передать локатор или метод поиска и имя элемента
        :param locator: локатор элемента
        :param method: метод поиска элемента
        :param name: value для поиска элемента, если role, в формате "role:name"
        :return:
        """
        if not locator:
            match method:
                case "test_id":
                    locator = self.page.get_by_test_id(value)
                case "role":
                    role, name = value.split(":", 1)
                    locator = self.page.get_by_role(role, name=name)
                case "text":
                    locator = self.page.get_by_text(value)

        if locator.count():
            locator.click()

    def click_and_catch_page(self, locator: Locator, timeout=30) -> Page:
        """
        Кликает по элементу и ждет появления страницы, ловит и возвращает ее
        :param locator: локатор элемента
        :return: страница
        """
        with self.context.expect_page(timeout=timeout*1000) as page_catcher:
            locator.click()
        return page_catcher.value
