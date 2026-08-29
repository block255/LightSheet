"""互译写方向测试：replay_cfg → 公式模板（运算/统计/计数 + 不可译）。"""
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from models.formula_translate import script_to_formula_template

def check(name, cond):
    if not cond:
        raise AssertionError('FAIL: ' + name)
    print('PASS:', name)

# ==== 运算类 ====
print('--- 运算类 ---')
def op_cfg(s0, s1):
    return {'direction': '以列为单位',
            'operands_raw': [dict(s0), dict(s1)],
            'output': {'target': 'column', 'index': 2}}

add = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1})
check('加法 列A+列B', script_to_formula_template(add, '加法脚本.py') == '=A{r}+B{r}')

sub = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 1})
check('减法 列A-1', script_to_formula_template(sub, '减法脚本.py') == '=A{r}-1')

mul = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1})
check('乘法 列A*列B', script_to_formula_template(mul, '乘法脚本.py') == '=A{r}*B{r}')

div = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1})
check('除法 列A/列B', script_to_formula_template(div, '除法脚本.py') == '=A{r}/B{r}')

exp = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1})
check('指数 列A^列B', script_to_formula_template(exp, '指数脚本.py') == '=A{r}^B{r}')

log = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1})
check('对数 LOG(真数,底数)', script_to_formula_template(log, '对数脚本.py') == '=LOG(B{r}, A{r})')

trig = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig['function'] = 'sin'
check('三角 SIN(列A)', script_to_formula_template(trig, '三角脚本.py') == '=SIN(A{r})')

trig_angle = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig_angle['function'] = 'sin'; trig_angle['angle_unit'] = '角度制'
check('三角角度 SIN(RADIANS)', script_to_formula_template(trig_angle, '三角脚本.py')
      == '=SIN(RADIANS(A{r}))')

trig_sec = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig_sec['function'] = 'sec'; trig_sec['angle_unit'] = '角度制'
check('三角角度 sec=1/COS(RADIANS)',
      script_to_formula_template(trig_sec, '三角脚本.py') == '=1/COS(RADIANS(A{r}))')

trig_cot = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig_cot['function'] = 'cot'
check('三角弧度 cot=1/TAN', script_to_formula_template(trig_cot, '三角脚本.py')
      == '=1/TAN(A{r})')

trig_asin = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig_asin['function'] = 'arcsin'; trig_asin['angle_unit'] = '角度制'
check('三角角度 arcsin=DEGREES(ASIN)',
      script_to_formula_template(trig_asin, '三角脚本.py') == '=DEGREES(ASIN(A{r}))')

trig_atan = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 0})
trig_atan['function'] = 'arctan'
check('三角弧度 arctan=ATAN', script_to_formula_template(trig_atan, '三角脚本.py')
      == '=ATAN(A{r})')

# 常数槽
addc = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'constant', 'value': 3.0})
check('加法 列A+3', script_to_formula_template(addc, '加法脚本.py') == '=A{r}+3')

# 剪贴板槽不译
clip = op_cfg({'kind': 'column', 'index': 0}, {'kind': 'clipboard', 'value': '1\n2'})
check('剪贴板槽不译', script_to_formula_template(clip, '加法脚本.py') is None)

# 文本计算元不译
txt = op_cfg({'kind': 'text', 'value': 'a'}, {'kind': 'text', 'value': 'b'})
txt['operands_text'] = True
check('文本计算元不译', script_to_formula_template(txt, '字符串加法脚本.py') is None)

# ==== 统计类 ====
print('--- 统计类 ---')
avg_col = {'direction': '对列处理', 'range': [0, 0, 5, 6],
           'output': {'target': 'row', 'index': 6}}
check('平均值 对列处理', script_to_formula_template(avg_col, '平均值脚本.py')
      == '=AVERAGE({c}1:{c}6)')

sum_col = dict(avg_col)
check('求和 对列处理', script_to_formula_template(sum_col, '求和脚本.py')
      == '=SUM({c}1:{c}6)')

max_row = {'direction': '对行处理', 'range': [0, 0, 13, 7],
           'output': {'target': 'column', 'index': 7}}
check('最大值 对行处理', script_to_formula_template(max_row, '最大值脚本.py')
      == '=MAX(A{r}:H{r})')

min_row = dict(max_row)
check('最小值 对行处理', script_to_formula_template(min_row, '最小值脚本.py')
      == '=MIN(A{r}:H{r})')

range_ = dict(avg_col)
check('极差 MAX-MIN', script_to_formula_template(range_, '极差脚本.py')
      == '=MAX({c}1:{c}6)-MIN({c}1:{c}6)')

var = dict(avg_col)
check('方差', script_to_formula_template(var, '方差脚本.py') == '=VAR({c}1:{c}6)')

stdev = dict(avg_col)
check('标准差', script_to_formula_template(stdev, '标准差脚本.py') == '=STDEV({c}1:{c}6)')

# 分位数（2026-08-29 起可译：MEDIAN / PERCENTILE.INC）
q_col = dict(avg_col); q_col['quantile'] = 0.5
check('分位数中位数 MEDIAN', script_to_formula_template(q_col, '分位数脚本.py')
      == '=MEDIAN({c}1:{c}6)')
q_manual = dict(avg_col); q_manual['quantile'] = 0.25
check('分位数手动 PERCENTILE.INC',
      script_to_formula_template(q_manual, '分位数脚本.py')
      == '=PERCENTILE.INC({c}1:{c}6, 0.25)')
q_row = {'direction': '对行处理', 'range': [0, 0, 13, 7],
         'output': {'target': 'column', 'index': 7}, 'quantile': 0.5}
check('分位数对行 MEDIAN', script_to_formula_template(q_row, '分位数脚本.py')
      == '=MEDIAN(A{r}:H{r})')

# ==== 计数（按行/列分组）====
print('--- 计数 ---')
count = {'direction': '对列处理', 'range': [0, 1, 5, 6],
         'operator': '>=', 'constant': '3',
         'output': {'target': 'row', 'index': 6}}
check('计数对列 COUNTIF({c})', script_to_formula_template(count, '计数脚本.py')
      == '=COUNTIF({c}1:{c}6, ">=3")')

count_neq = dict(count); count_neq['operator'] = '≠'
check('计数 ≠ 转 <>', script_to_formula_template(count_neq, '计数脚本.py')
      == '=COUNTIF({c}1:{c}6, "<>3")')

count_row = dict(count)
count_row['direction'] = '对行处理'
count_row['output'] = {'target': 'column', 'index': 7}
check('计数对行 COUNTIF({r})', script_to_formula_template(count_row, '计数脚本.py')
      == '=COUNTIF(B{r}:G{r}, ">=3")')

count_strict = dict(count); count_strict['operator'] = '≡'
check('计数 ≡ 严格相等不译', script_to_formula_template(count_strict, '计数脚本.py') is None)

# ==== 检定（IF+COUNTIF 组合，部分类型）====
print('--- 检定 ---')
inspect_exist = {'direction': '对列处理', 'range': [0, 0, 5, 6],
                 'operator': '>', 'constant': '2',
                 'inspect_type': '存在判定', 'pass_result': 1, 'fail_result': 0,
                 'output': {'target': 'row', 'index': 6}}
check('检定存在判定 IF(COUNTIF>0)',
      script_to_formula_template(inspect_exist, '检定脚本.py')
      == '=IF(COUNTIF({c}1:{c}6, ">2")>0, 1, 0)')

inspect_num = dict(inspect_exist)
inspect_num['inspect_type'] = '存在型数量自定义'; inspect_num['type_value'] = 3
check('检定数量 IF(COUNTIF>=N)',
      script_to_formula_template(inspect_num, '检定脚本.py')
      == '=IF(COUNTIF({c}1:{c}6, ">2")>=3, 1, 0)')

inspect_ratio = dict(inspect_exist)
inspect_ratio['inspect_type'] = '存在型比例自定义'
inspect_ratio['type_value'] = 0.5
inspect_ratio['pass_result'] = '通过'; inspect_ratio['fail_result'] = '不通过'
check('检定比例 IF(COUNTIF/COUNTA>=P)',
      script_to_formula_template(inspect_ratio, '检定脚本.py')
      == '=IF(COUNTIF({c}1:{c}6, ">2")/COUNTA({c}1:{c}6)>=0.5, "通过", "不通过")')

inspect_any = dict(inspect_exist)
inspect_any['inspect_type'] = '任意判定'
check('检定任意判定不译', script_to_formula_template(inspect_any, '检定脚本.py') is None)

# ==== 众数（2026-08-29：默认模式译 MODE.SNGL，精确模式不译）====
print('--- 众数 ---')
mode_cfg = {'direction': '对列处理', 'range': [0, 0, 5, 6],
            'output': {'target': 'row', 'index': 6}, 'mode': '默认'}
check('众数默认 MODE.SNGL', script_to_formula_template(mode_cfg, '众数脚本.py')
      == '=MODE.SNGL({c}1:{c}6)')
mode_precise = dict(mode_cfg)
mode_precise['mode'] = '精确'
check('众数精确不译', script_to_formula_template(mode_precise, '众数脚本.py')
      is None)
mode_old = dict(mode_cfg)
mode_old.pop('mode')
check('众数无mode(旧条目)默认译',
      script_to_formula_template(mode_old, '众数脚本.py') == '=MODE.SNGL({c}1:{c}6)')
check('空 operands None', script_to_formula_template(
    {'operands_raw': [{'kind': 'column', 'index': 0}]}, '加法脚本.py') is None)
check('无配置返回 None', script_to_formula_template({}, '加法脚本.py') is None)

print()
print('ALL FORMULA BRIDGE TESTS PASSED')
print('ALL FORMULA BRIDGE TESTS PASSED')
print('ALL FORMULA BRIDGE TESTS PASSED')
