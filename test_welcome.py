import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from bot import handle, WELCOME, instagram_nickname_link, main_menu
from catalog import TELEGRAM_URL, INSTAGRAM_URL
from payments import Store, Prices
from test_payments import Fake, callback
from test_invitations import message


class ReadHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.text=''; self.stack=[]; self.links=[]; self.bold=[]
    def handle_starttag(self,tag,attrs):
        self.stack.append(tag)
        if tag=='a': self.links.append(dict(attrs)['href'])
    def handle_endtag(self,tag):
        assert self.stack.pop()==tag
    def handle_data(self,data):
        self.text+=data
        if 'b' in self.stack: self.bold.append(data)


class WelcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db')
        self.api=Fake(); self.prices=Prices('','')
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def test_welcome_has_valid_html_bold_name_links_and_date(self):
        parser=ReadHTML(); parser.feed(WELCOME)
        self.assertFalse(parser.stack)
        self.assertLessEqual(len(parser.text.encode('utf-16-le'))//2,4096)
        self.assertIn('Надії Царенко',' '.join(parser.bold))
        self.assertIn('16.09.1998',parser.bold)
        self.assertEqual(parser.links,[TELEGRAM_URL,INSTAGRAM_URL])
        self.assertIn('Прогноз на рік:',parser.text)
        self.assertIn('Прогноз на місяць:',parser.text)
    def test_start_and_info_show_welcome_without_changing_access(self):
        self.store.set_current_birth(7,'16.09.1998'); self.store.set_section(7,'money')
        handle(self.api,message('/start'),self.store,self.prices)
        data=self.api.calls[-1][1]
        self.assertEqual(data['text'],WELCOME); self.assertEqual(data['parse_mode'],'HTML')
        self.assertEqual(instagram_nickname_link('sendMessage',data),data)
        self.assertEqual(self.store.section(7),'portrait')
        self.assertEqual(self.store.current_birth(7),'16.09.1998')
        self.assertEqual(self.store.owned(7,'16.09.1998'),{21,30})
        self.store.set_section(7,'money')
        handle(self.api,callback('info'),self.store,self.prices)
        self.assertEqual(self.api.calls[-1][1]['text'],WELCOME)
        self.assertEqual(self.store.section(7),'money')
        handle(self.api,message('/info'),self.store,self.prices)
        self.assertEqual(self.api.calls[-1][1]['text'],WELCOME)
        self.assertIn('info',str(main_menu()))


if __name__=='__main__': unittest.main()
