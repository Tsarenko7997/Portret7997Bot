import unittest
from portrait import calculate, reduce22
from bot import handle
from payments import Store, Prices
from tempfile import TemporaryDirectory

class PortraitTests(unittest.TestCase):
    def test_reference_full(self):
        p,_=calculate('16.09.1998')
        values=[16,9,5,3,14,17,8,4,7,4,3,12,14,14]
        for i,n in enumerate(values,1): self.assertEqual(p[f'П{i}'],n)
        expected={'П15а':6,'П15б':2,'П16':16,'П17':20,'П18':7,'П19':20,'П20':9,'П21':20,'П30':2,'A':19,'B':12,'C':1,'D':19,'E':20,'F':9,'G1':20,'G2':21,'H':17,'Кп':21,'J':13}
        for k,v in expected.items(): self.assertEqual(p[k],v,k)
    def test_other_screenshots(self):
        for date,expected in [('01.01.2000',[1,1,2,2,3,5,4,6,10,8,10,7,8,14,20]),('22.12.1999',[22,12,6,12,18,8,18,20,16,20,10,20,4,12,10])]:
            p,_=calculate(date)
            for k,v in zip([1,2,3,4,5,6,7,8,12,13,14,19,20,21,30],expected): self.assertEqual(p[f'П{k}'],v)
    def test_dates(self):
        calculate('29.02.2000')
        for value in ['29.02.1900','31.04.2000','1.1.2000','00.01.2000','01.01.2999','hello']:
            with self.assertRaises(ValueError): calculate(value)
    def test_zero_and_reduction(self):
        self.assertEqual([reduce22(x) for x in (0,22,44,45,78)],[22,22,22,1,12])
    def test_p15_uses_unreduced_sum(self):
        p,_=calculate('01.03.1998')
        # Raw sum 26, minus P7=9 => 17. Reducing first would give 5.
        self.assertEqual(p['П15а'],17)
    def test_negative_difference(self):
        p,_=calculate('05.03.2000')
        s=p['П9']+p['П10']+p['П11']
        self.assertLess(s,p['П7'])
        self.assertEqual(p['П15а'],6)
    def test_transport_dispatch(self):
        class Fake:
            def __init__(self): self.calls=[]
            def call(self,*args): self.calls.append(args)
            def say(self,*args,**kwargs): self.calls.append(('sendMessage',args,kwargs))
        with TemporaryDirectory() as d:
            s=Store(d+'/test.sqlite3');prices=Prices('', '');f=Fake()
            handle(f,{'message':{'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'16.09.1998'}},s,prices)
            photo=next(c for c in f.calls if c[0]=='sendPhoto')
            self.assertTrue(photo[2][1].startswith(b'\x89PNG'))
            for action in ['calc','png']:
                handle(f,{'callback_query':{'id':'1','from':{'id':1},'data':action+':16.09.1998','message':{'chat':{'id':1,'type':'private'}}}},s,prices)
            self.assertEqual(f.calls[-1][0],'sendDocument');s.close()

if __name__=='__main__': unittest.main()
