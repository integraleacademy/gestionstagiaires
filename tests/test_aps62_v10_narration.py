"""Do not publish a successful TTS stream if its real audio is incomplete."""
import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from scripts.render_aps62_v8 import reliable_speech


class CompleteNarrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_take_is_retried_without_shortening_captions_or_padding_sound(self):
        cue=[{'start':562.744,'end':565.587,'text':"L'historique contribue à la fiabilité du registre."}]
        takes=AsyncMock(side_effect=[(Path('partial.mp3'),cue),(Path('complete.mp3'),cue)])
        with patch('scripts.render_aps62_v8.speech',takes), patch('scripts.render_aps62_v8.duration',side_effect=[563.928,566.304]), patch('scripts.render_aps62_v8.run') as decode:
            audio,actual_cues=await reliable_speech('Texte intégral.',Path('/tmp/aps62-13-01'),asyncio.Semaphore(1))
        self.assertEqual(audio,Path('complete.mp3'))
        decode.assert_called_once()
        self.assertIn('complete.mp3', decode.call_args.args[0])
        self.assertEqual(actual_cues,cue)
        self.assertEqual([call.args[2] for call in takes.await_args_list],[0,1])
        self.assertTrue(all(call.args[0]=='Texte intégral.' for call in takes.await_args_list))

    async def test_three_incomplete_takes_stop_publication(self):
        takes=AsyncMock(return_value=(Path('incomplete.mp3'),[{'start':562,'end':565.587,'text':'Fin.'}]))
        with patch('scripts.render_aps62_v8.speech',takes), patch('scripts.render_aps62_v8.duration',return_value=563.928):
            with self.assertRaisesRegex(RuntimeError,'after three takes'):
                await reliable_speech('Texte intégral.',Path('/tmp/aps62-13-01'),asyncio.Semaphore(1))
        self.assertEqual(takes.await_count,3)
