"""Private Pro program metadata and arcana; never bundled with the public image."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache


def _text(value, limit=1800):
    if not isinstance(value, str) or not value.strip() or len(value)>limit:
        raise ValueError('Invalid program text')


@lru_cache(maxsize=1)
def read_program_catalog():
    count=int(os.environ.get('PROGRAMS_XZ_PARTS','0'))
    if not 1<=count<=20:raise ValueError('Invalid program catalog parts')
    packed=''.join(os.environ[f'PROGRAMS_XZ_B64_{i}'] for i in range(1,count+1))
    raw=lzma.decompress(base64.b64decode(packed,validate=True))
    if hashlib.sha256(raw).hexdigest()!=os.environ['PROGRAMS_SHA256']:
        raise ValueError('Invalid program catalog checksum')
    data=json.loads(raw)
    if set(data)!={'programs','arcana'} or set(data['programs'])!=set(map(str,range(1,22))) or set(data['arcana'])!=set(map(str,range(1,23))):
        raise ValueError('Incomplete program catalog')
    for program in data['programs'].values():
        if set(program)!={'title','overview','questions'}:raise ValueError('Invalid program fields')
        _text(program['title'],100);_text(program['overview'])
        if not isinstance(program['questions'],list) or len(program['questions'])!=6:raise ValueError('Expected 6 questions')
        for question in program['questions']:
            if set(question)!={'question','lens','practical'}:raise ValueError('Invalid question fields')
            for value in question.values():_text(value)
    for arcanum in data['arcana'].values():
        if set(arcanum)!={'name','keywords','general','positive','difficulties','practical','facets'}:raise ValueError('Invalid arcanum fields')
        for key,value in arcanum.items():
            if key!='facets':_text(value)
        if not isinstance(arcanum['facets'],dict) or set(arcanum['facets'])!={'communication','money','work','learning','relations','spirit','creativity'}:
            raise ValueError('Invalid program facets')
        for value in arcanum['facets'].values():_text(value)
    return data


def program_entry(program):
    if type(program) is not int or not 1<=program<=21:raise ValueError('Invalid program')
    return read_program_catalog()['programs'][str(program)]


def program_description(program,question,arcanum):
    if type(question) is not int or not 1<=question<=6 or type(arcanum) is not int or not 1<=arcanum<=22:
        raise ValueError('Invalid program question or arcanum')
    entry=program_entry(program)
    q=entry['questions'][question-1]
    a=read_program_catalog()['arcana'][str(arcanum)]
    topic={1:'communication',3:'money',4:'work',5:'learning',6:'relations',7:'work',9:'spirit',10:'spirit',14:'work',17:'creativity',20:'relations'}.get(program)
    focus=a['facets'][topic]+' ' if topic else ''
    return '\n\n'.join([
        f'Програма {program} · '+entry['title'],
        f'Питання {question} · '+q['question'],
        f'Аркан {arcanum} · '+a['name'],
        'Ключові слова. '+a['keywords'],
        'Відповідь. '+q['lens']+' '+focus+a['general'],
        'Позитивні прояви. '+a['positive'],
        'Можливі труднощі. '+a['difficulties'],
        'Практичний орієнтир. '+q['practical']+' '+a['practical'],
    ])
