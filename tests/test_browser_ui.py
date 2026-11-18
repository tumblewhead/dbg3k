"""Opt-in real Chromium interactions. No target or GDB is started by the viewer."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('DBG3K_BROWSER_TEST') == '1', 'opt-in Playwright browser check')
class BrowserUiTests(unittest.TestCase):
    def test_full_history_profiles_raw_records_and_local_file_boundary(self):
        from playwright.sync_api import sync_playwright, expect
        from test_kodama import sample
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            data = folder / 'sample.json'
            data.write_text(json.dumps(sample()))
            fixture = folder / 'history.jsonl'
            env = dict(os.environ, DBG3K_BROWSER_FIXTURE=str(fixture))
            subprocess.run(['node', str(ROOT / 'tests/browser_model_test.js'), str(data)],
                           env=env, capture_output=True, check=True, timeout=60)
            bad = folder / 'bad.jsonl'
            bad.write_text('not-json\n{"interrupted":')
            server = subprocess.Popen([sys.executable, '-m', 'dbg3k.history_browser', '--port', '0'],
                                      cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                url = server.stdout.readline().strip().removeprefix('dbg3k history: ')
                self.assertTrue(url.startswith('http://127.0.0.1:'), url)
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
                    page = browser.new_page(viewport={'width': 1512, 'height': 1050}, device_scale_factor=1)
                    errors, requests, dialogs = [], [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('request', lambda r: requests.append((r.method, r.url)))
                    page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
                    page.goto(url)
                    page.locator('#file').set_input_files(fixture)
                    expect(page.locator('#workspace')).to_be_visible(timeout=30000)
                    page.locator('#session').select_option('one')
                    page.locator('#capture').select_option('fixture')
                    expect(page.locator('#sample-count')).to_have_text('6,201')
                    expect(page.locator('#cursor-label')).to_contain_text('Sample 1 /', timeout=30000)
                    page.locator('#latest').click()
                    expect(page.locator('#cursor-label')).to_contain_text('Sample 6,201 /', timeout=30000)
                    expect(page.locator('#tasks')).to_contain_text('@e1')
                    page.locator('#oldest').click()
                    expect(page.locator('#cursor-label')).to_contain_text('Sample 1 /')
                    page.locator('#jump').fill('5000'); page.locator('#jump-button').click()
                    expect(page.locator('#sample-detail')).to_contain_text('CAPTURE GAP', timeout=30000)
                    expect(page.locator('#sample-detail')).to_contain_text('80')
                    page.locator('#columns').select_option('64')
                    expect(page.locator('#range-label')).to_contain_text('of 6,201')
                    page.locator('#pan').fill('3000')
                    expect(page.locator('#cursor-label')).to_contain_text('Sample 3,001 /', timeout=30000)
                    page.locator('#lanes').focus(); page.keyboard.press('ArrowRight')
                    expect(page.locator('#cursor-label')).to_contain_text('Sample 3,002 /')
                    page.locator('[data-tab=profiling]').click()
                    expect(page.locator('#functions')).to_contain_text('worker<script>')
                    expect(page.locator('#functions')).to_contain_text('9,007,199,254,740,993,120')
                    page.locator('#sort').select_option('entries')
                    page.locator('.model-editor summary').click()
                    page.locator('#duration').fill('2'); page.locator('#apply-model').click()
                    expect(page.locator('#model-status')).to_contain_text('User-supplied cumulative target duration 2 s')
                    expect(page.locator('#profile-summary')).to_contain_text('µW')
                    with page.expect_download() as info: page.locator('#export-profile').click()
                    download = folder / 'profile.csv'; info.value.save_as(download)
                    self.assertIn('9007199254740993120', download.read_text())
                    self.assertIn('ua_per_mhz', download.read_text())
                    page.locator('[data-tab=stack]').click()
                    page.locator('#record-kind').select_option('observation')
                    page.locator('#record-seq').fill('1'); page.locator('#record-next').click()
                    expect(page.locator('#raw')).to_contain_text('"status": "error"')
                    expect(page.locator('#raw')).to_contain_text('"expression": "missing"')
                    page.locator('#record-kind').select_option('instruction_profile')
                    page.locator('#record-seq').fill('1'); page.locator('#record-next').click()
                    expect(page.locator('#record-label')).to_contain_text('instruction_profile')
                    with page.expect_download() as info: page.locator('#record-download').click()
                    original = folder / 'original-record.json'; info.value.save_as(original)
                    self.assertIn('"total":9007199254740993123', original.read_text())
                    page.locator('#session').select_option('two')
                    expect(page.locator('#sample-count')).to_have_text('0')
                    expect(page.locator('#energy-total')).to_have_text('Unavailable')
                    page.locator('#file').set_input_files(bad)
                    expect(page.locator('#status')).to_contain_text('Cannot open recording', timeout=30000)
                    expect(page.locator('#workspace')).to_be_hidden()
                    page.locator('#file').set_input_files(fixture)
                    expect(page.locator('#workspace')).to_be_visible(timeout=30000)
                    receipt = os.environ.get('DBG3K_BROWSER_RECEIPT')
                    real = os.environ.get('DBG3K_BROWSER_REAL_TRACE')
                    if real:
                        page.locator('#file').set_input_files(real)
                        expect(page.locator('#workspace')).to_be_visible(timeout=30000)
                        expect(page.locator('#identity')).to_contain_text('named bodies')
                        page.locator('[data-tab=timeline]').click()
                        page.locator('#latest').click()
                        expect(page.locator('#tasks')).to_contain_text('Pipeline', timeout=30000)
                        expect(page.locator('#pool-total')).to_contain_text('occupied')
                        page.locator('[data-tab=profiling]').click()
                        expect(page.locator('#profile-provenance')).to_contain_text('recorded ELF symbol catalog', timeout=30000)
                        expect(page.locator('#functions')).not_to_be_empty()
                    if receipt:
                        dest = Path(receipt); dest.mkdir(parents=True, exist_ok=True)
                        page.locator('[data-tab=profiling]').click()
                        page.screenshot(path=str(dest / 'profile-dark.png'), full_page=True)
                        page.locator('[data-tab=timeline]').click()
                        page.screenshot(path=str(dest / 'timeline-dark.png'), full_page=True)
                        page.locator('#theme').click()
                        page.screenshot(path=str(dest / 'timeline-light.png'), full_page=True)
                        page.set_viewport_size({'width': 430, 'height': 932})
                        page.screenshot(path=str(dest / 'narrow.png'), full_page=True)
                        (dest / 'browser.json').write_text(json.dumps({'errors': errors, 'dialogs': dialogs,
                            'requests': requests, 'browser': browser.version}, indent=2) + '\n')
                    self.assertFalse(errors, errors)
                    self.assertFalse(dialogs, dialogs)
                    self.assertTrue(all(method == 'GET' and address.startswith(url) for method, address in requests), requests)
                    self.assertEqual(page.locator('img').count(), 0)
                    browser.close()
            finally:
                server.terminate(); server.wait(timeout=5)
                server.stdout.close(); server.stderr.close()
