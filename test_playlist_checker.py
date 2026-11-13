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


if __name__ == '__main__':
    unittest.main()
