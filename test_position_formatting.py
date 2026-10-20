import unittest
from catalog import POSITIONS, description, position_meaning, chunks, INSTAGRAM_URL, TELEGRAM_HANDLE
from portrait import calculate
from bot import instagram_nickname_link, KARMA_INTRO


def entity_text(text,entity):
    data=text.encode('utf-16-le')
    return data[entity['offset']*2:(entity['offset']+entity['length'])*2].decode('utf-16-le')


class PositionFormattingTests(unittest.TestCase):
    def test_all_headers_match_overview_meanings(self):
        calculated,_=calculate('16.09.1998')
        for n,p in POSITIONS.items():
            text=description(n,'16.09.1998',calculated)
            self.assertEqual(text.splitlines()[0],f"Позиція {n} ({p['key']}) · {position_meaning(p)}")
            rendered=instagram_nickname_link('sendMessage',{'text':text})
            bold=[entity_text(rendered['text'],e) for e in rendered['entities'] if e['type']=='bold']
            self.assertEqual(bold[0],text.splitlines()[0])
            for heading in ['Позитивні прояви','Можливі труднощі','Внутрішні установки та блоки']:
                self.assertIn(heading,bold)
            self.assertEqual(sum(e['type']=='text_link' for e in rendered['entities']),1)
    def test_continuation_chunks_get_bold_without_instagram_url(self):
        text='✨\n\nПозитивні прояви. Добре.\n\nМожливі труднощі. Складно.\n\nВнутрішні установки та блоки. Текст.'
        rendered=instagram_nickname_link('sendMessage',{'text':text})
        self.assertEqual([entity_text(rendered['text'],e) for e in rendered['entities']],
                         ['Позитивні прояви','Можливі труднощі','Внутрішні установки та блоки'])
        self.assertEqual(rendered['text'],text)
    def test_link_and_bold_offsets_after_emoji_and_url_replacement(self):
        original={'text':'✨ '+INSTAGRAM_URL+'\n\nМожливі труднощі. Приклад.'}
        result=instagram_nickname_link('sendMessage',original)
        self.assertEqual(entity_text(result['text'],result['entities'][0]),TELEGRAM_HANDLE)
        self.assertEqual(entity_text(result['text'],result['entities'][1]),'Можливі труднощі')
        self.assertEqual(result['entities'][0]['url'],INSTAGRAM_URL)
        self.assertIn(INSTAGRAM_URL,original['text'])
    def test_existing_formatting_and_unrelated_messages_are_preserved(self):
        for data in [{'text':'Звичайне повідомлення'},
                     {'text':'Можливі труднощі. Текст.','parse_mode':'HTML'},
                     {'text':'Можливі труднощі. Текст.','entities':[{'type':'bold','offset':0,'length':1}]}]:
            self.assertEqual(instagram_nickname_link('sendMessage',data),data)
    def test_each_split_part_has_valid_entities(self):
        p,_=calculate('16.09.1998')
        for part in chunks(description(15,'16.09.1998',p),limit=500):
            rendered=instagram_nickname_link('sendMessage',{'text':part})
            for entity in rendered.get('entities',[]):
                self.assertTrue(entity_text(rendered['text'],entity))

    def test_karma_and_money_headings(self):
        examples=[
            ('Плюсова карма · Позиція 1',['Ваш ресурс','Можливі прояви','Що може послаблювати ресурс']),
            ('Мінусова карма · Позиція 1',['Кармічна тема','Можливі труднощі','Внутрішні блоки','Сильні сторони']),
            ('Грошове призначення · 16.09.1998',['Ваш акцент'])]
        for title,headings in examples:
            text=title+'\nДата народження: 16.09.1998\n\nАркан 3 · Назва\n\n'
            text+='\n\n'.join(heading+'. Текст.' for heading in headings)
            text+='\n\nInstagram: '+INSTAGRAM_URL
            result=instagram_nickname_link('sendMessage',{'text':text})
            bold=[entity_text(result['text'],e) for e in result['entities'] if e['type']=='bold']
            self.assertEqual(bold,[title,'Аркан 3 · Назва']+headings)
            link=next(e for e in result['entities'] if e['type']=='text_link')
            self.assertEqual(entity_text(result['text'],link),TELEGRAM_HANDLE)
            self.assertEqual(link['url'],INSTAGRAM_URL)

    def test_karma_intro_caption_headings_links_and_limit(self):
        text='Карма +/− · 16.09.1998\n\n'+KARMA_INTRO+'\n\nInstagram: '+INSTAGRAM_URL
        text+='\n\nНатисніть позицію плюсової або мінусової карми нижче, щоб прочитати її опис.'
        text+='\n\nДля нового розрахунку надішліть іншу дату.'
        result=instagram_nickname_link('sendPhoto',{'caption':text})
        bold=[entity_text(result['caption'],e) for e in result['caption_entities'] if e['type']=='bold']
        self.assertEqual(bold,['Карма','Позитивна карма','Негативна карма'])
        self.assertLessEqual(len(result['caption'].encode('utf-16-le'))//2,1024)
        self.assertTrue(any(e['type']=='text_link' for e in result['caption_entities']))


if __name__=='__main__': unittest.main()
