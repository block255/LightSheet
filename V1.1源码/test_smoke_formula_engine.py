"""公式求值引擎测试：词法/语法/四则优先级/区域/表广播/19 函数/错误值/相对展开。"""
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from models.table_data import TableData
from models.formula_engine import (
    EvalContext, evaluate, parse_formula, ErrorValue,
    expand_template, ERR_DIV0, ERR_VALUE, ERR_REF, ERR_NAME,
)

def check(name, cond):
    if not cond:
        raise AssertionError('FAIL: ' + name)
    print('PASS:', name)

def make_model():
    """构造测试表格：
      A1=2  B1=3  C1=5
      A2=4  B2=6  C2=10
      A3=10 B3=2  C3=12
      A4=1  B4=0
    """
    t = TableData()
    t.load_2d([['2', '3', '5'], ['4', '6', '10'], ['10', '2', '12'],
               ['1', '0', '']])
    return t

def ev(f, model=None):
    ctx = EvalContext(model or make_model())
    return evaluate(f, ctx)

def scalar(v):
    from models.formula_engine import TableValue
    if isinstance(v, TableValue):
        return v.as_scalar()
    return v

# ==== 词法/语法/优先级 ====
print('--- 语法与优先级 ---')
check('A1+B1', scalar(ev('=A1+B1')) == 5.0)
check('A1+B1*C1（乘优先）', scalar(ev('=A1+B1*C1')) == 17.0)
check('(A1+B1)*C1（括号）', scalar(ev('=(A1+B1)*C1')) == 25.0)
check('A2^2（指数）', scalar(ev('=A2^2')) == 16.0)
check('A3/A2', scalar(ev('=A3/A2')) == 2.5)
check('A3%', scalar(ev('=A3%')) == 0.1)
check('A1<B1', scalar(ev('=A1<B1')) is True)
check('A1>=B1', scalar(ev('=A1>=B1')) is False)
check('-A1+10', scalar(ev('=-A1+10')) == 8.0)
check('A1&B1 文本连接', scalar(ev('="列"&A1')) == '列2')
check('比较 2=2', scalar(ev('=2=2')) is True)

# ==== 区域与聚合 ====
print('--- 区域聚合 ---')
check('SUM(A1:A2)', scalar(ev('=SUM(A1:A2)')) == 6.0)
check('SUM(A1:C3) 全区域', scalar(ev('=SUM(A1:C3)')) == 54.0)
check('AVERAGE(A1:A4)', scalar(ev('=AVERAGE(A1:A4)')) == 4.25)
check('MAX(A1:C3)', scalar(ev('=MAX(A1:C3)')) == 12.0)
check('MIN(A1:C3)', scalar(ev('=MIN(A1:C3)')) == 2.0)
check('COUNT(A1:A4)', scalar(ev('=COUNT(A1:A4)')) == 4.0)
check('COUNTA(A1:A4)', scalar(ev('=COUNTA(A1:A4)')) == 4.0)
check('VAR(A1:A4)', round(scalar(ev('=VAR(A1:A4)')), 4) == 16.25)
check('STDEV(A1:A4)', round(scalar(ev('=STDEV(A1:A4)')), 6) == 4.031129)
check('COUNTIF(A1:A3,">3")', scalar(ev('=COUNTIF(A1:A3,">3")')) == 2.0)
check('COUNTIF(A1:A4,"<>2")', scalar(ev('=COUNTIF(A1:A4,"<>2")')) == 3.0)

# ==== 表值运算 ====
print('--- 表值（区域运算/广播）---')
from models.formula_engine import TableValue
v = ev('=A1:A2+B1:B2')
check('区域+区域 对齐', isinstance(v, TableValue)
      and v.rows == [[5.0], [10.0]] and v.height == 2)
v2 = ev('=A1:B2*2')
check('区域*标量 广播', isinstance(v2, TableValue)
      and v2.rows == [[4.0, 6.0], [8.0, 12.0]])

# ==== 19 个函数 ====
print('--- 函数 ---')
check('SQRT(9)', scalar(ev('=SQRT(9)')) == 3.0)
check('LOG10(100)', scalar(ev('=LOG10(100)')) == 2.0)
check('ABS(-5)', scalar(ev('=ABS(-5)')) == 5.0)
check('ROUND(3.7)', scalar(ev('=ROUND(3.7)')) == 4.0)
check('INT(3.9)', scalar(ev('=INT(3.9)')) == 3.0)
check('MOD(10,3)', scalar(ev('=MOD(10,3)')) == 1.0)
check('POWER(2,3)', scalar(ev('=POWER(2,3)')) == 8.0)
check('IF(A1>1,"大","小")', scalar(ev('=IF(A1>1,"大","小")')) == '大')
check('AND(A1>0,B1>0)', scalar(ev('=AND(A1>0,B1>0)')) is True)
check('OR(A1>1,B1>5)', scalar(ev('=OR(A1>1,B1>5)')) is True)
check('OR(A1>5,B1>5)', scalar(ev('=OR(A1>5,B1>5)')) is False)
check('NOT(A1>5)', scalar(ev('=NOT(A1>5)')) is True)
check('CONCATENATE("a","b")', scalar(ev('=CONCATENATE("a","b")')) == 'ab')
check('LEN("你好ab")', scalar(ev('=LEN("你好ab")')) == 4.0)
check('VALUE("12.5")', scalar(ev('=VALUE("12.5")')) == 12.5)
check('LEFT("hello",2)', scalar(ev('=LEFT("hello",2)')) == 'he')
check('RIGHT("hello",2)', scalar(ev('=RIGHT("hello",2)')) == 'lo')
check('MID("hello",2,3)', scalar(ev('=MID("hello",2,3)')) == 'ell')
check('SIN(0)', scalar(ev('=SIN(0)')) == 0.0)
check('COS(0)', scalar(ev('=COS(0)')) == 1.0)
check('TAN(0)', scalar(ev('=TAN(0)')) == 0.0)

# ==== 互译扩展函数（2026-08-29）====
print('--- 互译扩展函数 ---')
# A 列 = [2,4,10,1]（make_model）；排序 [1,2,4,10]
check('MEDIAN(A1:A4)', scalar(ev('=MEDIAN(A1:A4)')) == 3.0)
check('MEDIAN 空区域 #DIV/0!', scalar(ev('=MEDIAN(E1:E4)')) == ERR_DIV0)
check('PERCENTILE.INC 0.5（中位）', scalar(ev('=PERCENTILE.INC(A1:A4, 0.5)')) == 3.0)
check('PERCENTILE.INC 0.25 插值', scalar(ev('=PERCENTILE.INC(A1:A4, 0.25)')) == 1.75)
check('PERCENTILE 别名', scalar(ev('=PERCENTILE(A1:A4, 0.5)')) == 3.0)
check('PERCENTILE.INC k 越界 #DIV/0!',
      isinstance(scalar(ev('=PERCENTILE.INC(A1:A4, 1.5)')), ErrorValue))
check('RADIANS(180)≈π', round(scalar(ev('=RADIANS(180)')), 9) == round(3.141592654, 9))
check('DEGREES(π)≈180', round(scalar(ev('=DEGREES(3.141592653589793)')), 9) == 180.0)
check('ASIN(1)≈π/2', round(scalar(ev('=ASIN(1)')), 9) == round(1.570796327, 9))
check('ACOS(1)=0', scalar(ev('=ACOS(1)')) == 0.0)
check('ATAN(1)≈π/4', round(scalar(ev('=ATAN(1)')), 9) == round(0.785398163, 9))
check('SIN(RADIANS(90))≈1（角度转换闭环）',
      round(scalar(ev('=SIN(RADIANS(90))')), 9) == 1.0)
check('DEGREES(ASIN(1))≈90（反三角角度闭环）',
      round(scalar(ev('=DEGREES(ASIN(1))')), 9) == 90.0)
check('1/COS(0)=1（sec 拼式闭环）', scalar(ev('=1/COS(0)')) == 1.0)
check('PERCENTILE.INC 解析（点号函数名）',
      scalar(ev('=PERCENTILE.INC(A1:A4, 0.25)')) == 1.75)
# MODE.SNGL：并列取第一 / 全单次 #N/A
t_mode = TableData()
t_mode.load_2d([['5'], ['5'], ['7'], ['7'], ['9']])
ctx_m = EvalContext(t_mode)
check('MODE.SNGL 并列取第一', evaluate('=MODE.SNGL(A1:A5)', ctx_m) == 5.0)
t_mode2 = TableData()
t_mode2.load_2d([['1'], ['2'], ['3'], ['4']])
check('MODE.SNGL 全单次 #N/A',
      evaluate('=MODE.SNGL(A1:A4)', EvalContext(t_mode2)) == ErrorValue('#N/A'))

# ==== 错误值 ====
print('--- 错误值 ---')
check('除零 #DIV/0!', scalar(ev('=A1/0')) == ERR_DIV0)
check('A4/B4 除零（B4=0）', scalar(ev('=A4/B4')) == ERR_DIV0)
check('文本参与运算 #VALUE!',
      isinstance(scalar(ev('="abc"+1')), ErrorValue))
check('区域尺寸不匹配 #VALUE!',
      isinstance(ev('=A1:A3+B1:B2'), ErrorValue))
check('未知函数 #NAME?',
      isinstance(scalar(ev('=FOO(1)')), ErrorValue))
check('引用越界 #REF!', scalar(ev('=ZZ9999')) == ERR_REF)
check('网格内空格=空', scalar(ev('=Z99')) is None)
check('负数开方 #NUM!', scalar(ev('=SQRT(-1)')) == ErrorValue('#NUM!'))

# ==== 相对引用模板展开 ====
print('--- 相对引用展开 ---')
tpl = '=A{r}+B{r}'
check('模板展开 行1', expand_template(tpl, 0, 0) == '=A1+B1')
check('模板展开 行2', expand_template(tpl, 1, 0) == '=A2+B2')
check('模板展开 行10', expand_template(tpl, 9, 0) == '=A10+B10')

print()
print('ALL FORMULA ENGINE TESTS PASSED')
print('ALL FORMULA ENGINE TESTS PASSED')
print('ALL FORMULA ENGINE TESTS PASSED')
