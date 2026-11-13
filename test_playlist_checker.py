import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import playlist_checker as pc


class ParserTests(unittest.TestCase):
    def test_extinf_preserves_epg_and_clean_name(self):
        text = ('#EXTM3U\n#EXTINF:-1 tvg-id="one" tvg-logo="x" group-title="News",'
                'RUZIEV+ IPTV | Test\nhttps://example.org/live.ts\n')
        found = pc.parse_channels(text, 1, 'https://example.org/list.m3u')
        self.assertEqual(len(found), 1)
        self.assertIn('tvg-id="one"', found[0].extinf)
        self.assertIn('group-title="News"', found[0].extinf)
        self.assertTrue(found[0].extinf.endswith('Test'))

    def test_hls_manifest_single_channel(self):
        m3u = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nsegment001.ts\n'
        found = pc.parse_channels(m3u, 2, 'https://example.org/master.m3u8')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].url, 'https://example.org/master.m3u8')

    def test_options_are_preserved(self):
        text = ('#EXTM3U\n#EXTINF:-1,Test\n#EXTVLCOPT:http-referrer=https://player.example/\n'
                '#EXTVLCOPT:http-user-agent=Example-UA\nhttps://cdn.example/stream\n')
        found = pc.parse_channels(text, 1, 'https://example.org/list')
        self.assertEqual(found[0].referer, 'https://player.example/')
        self.assertEqual(found[0].user_agent, 'Example-UA')
        self.assertEqual(len(found[0].options), 2)

    def test_invalid_text_does_not_create_channel(self):
        self.assertEqual(pc.parse_channels('<html>Oops</html>', 1, 'https://a.test'), [])

    def test_atomic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'playlist.m3u'
            pc.write_atomic(target, '#EXTM3U\n')
            self.assertEqual(target.read_text(), '#EXTM3U\n')


class StatusTests(unittest.TestCase):
    def test_status_comments_are_idempotent_and_urls_unchanged(self):
        lines = ['# My own note', 'https://example.org/a.m3u?token=secret',
                 '', 'http://example.net/b.m3u']
        data = {
            1: {'total': 2, 'working': 1, 'download_error': None},
            2: {'total': 0, 'working': 0, 'download_error': 'HTTP 403'},
        }
        first = pc.status_sources_text(lines, data)
        second = pc.status_sources_text(first.splitlines(), data)
        self.assertEqual(first, second)
        self.assertEqual(first.count(pc.STATUS_PREFIX), 2)
        self.assertIn('# My own note', first)
        self.assertIn('https://example.org/a.m3u?token=secret', first)
        self.assertIn('🟡 ERROR | HTTP 403', first)

    def test_report_does_not_leak_url_credentials(self):
        report = {'timestamp_utc': '2026-11-13T00:00:00Z', 'sources_total': 1,
                  'channels_found': 0, 'channels_verified': 0, 'channels_rejected': 0,
                  'published': False}
        sources = ['https://user:secret@example.org/path?token=secret']
        data = {1: {'id': 1, 'total': 0, 'working': 0,
                    'download_error': 'HTTP 403'}}
        output = pc.markdown_status(sources, data, report)
        self.assertIn('example.org', output)
        self.assertNotIn('secret', output)
        self.assertNotIn('token=', output)

    def test_first_verified_baseline_is_zero(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pc, 'STATE_FILE', Path(d) / 'missing.json'):
                self.assertEqual(pc.verified_baseline(), 0)

    def test_saved_verified_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            state.write_text(json.dumps({'last_verified_channels': 1403}))
            with patch.object(pc, 'STATE_FILE', state):
                self.assertEqual(pc.verified_baseline(), 1403)


if __name__ == '__main__':
    unittest.main()
