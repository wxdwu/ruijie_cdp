"""临时单元测试：验证分支机构同公司识别逻辑（不连库）。"""
import sys, importlib.util, re

spec = importlib.util.spec_from_file_location(
    "company_dedup_test",
    r"e:\DevTools\ruijie_workspace\ruijie-cdp\backend\app\services\company_dedup\company_dedup.py",
)
mod = None
HAVE_MODULE = False
try:
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    HAVE_MODULE = True
except Exception as e:
    print("模块加载失败（依赖缺失），改用内联正则复刻验证:", e)
    mod = None

if HAVE_MODULE:
    fn = mod._branch_canonical
    pf = mod._parse_branch
else:
    _BRANCH_TAIL_WORDS = (
        "分公司|分厂|子公司|办事处|代表处|营销中心|销售中心|经营部|营业部|"
        "项目部|分理处|支公司|分店|门市部|门店|服务部|维修点"
    )
    _BRANCH_PARSE_RE = re.compile(
        r"^(?P<base>.+?)" r"(?P<ord>第[一二三四五六七八九十百零0-9]+)?"
        r"(?P<tail>" + _BRANCH_TAIL_WORDS + r")$"
    )
    _PAREN_GEO_RE = re.compile(r"^(?P<base>.+?)\s*[（(]([一-鿿]{1,12})[)）]\s*$")
    _SEP_GEO_RE = re.compile(r"^(?P<base>.+?)\s*[-—–·/]\s*([一-鿿]{1,12})$")
    _BRANCH_GEO_TOKENS = {"北京", "上海", "深圳", "广州", "杭州", "南京", "成都",
                          "武汉", "西安", "苏州", "青岛", "沈阳", "大连", "厦门", "宁波",
                          "东莞", "佛山", "珠海", "天津", "重庆", "河北", "山西", "江苏",
                          "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                          "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海"}
    _BRANCH_GEO_SUFFIXES = ("省", "市", "区", "县", "自治区", "特区", "州", "盟")

    def _strip_leading_geo(base):
        if not base:
            return base
        stripped = base
        changed = True
        while changed:
            changed = False
            for suf in _BRANCH_GEO_SUFFIXES:
                if stripped.endswith(suf):
                    idx = stripped.rfind(suf)
                    stripped = stripped[:idx]
                    changed = True
                    break
            if changed:
                continue
            for tok in _BRANCH_GEO_TOKENS:
                if stripped.endswith(tok):
                    stripped = stripped[: -len(tok)]
                    changed = True
                    break
        return stripped.strip()

    def _parse_branch(name):
        raw = name.strip()
        m = _BRANCH_PARSE_RE.match(raw)
        if m and m.group("tail"):
            return _strip_leading_geo(m.group("base").strip()), m.group("tail")
        m = _PAREN_GEO_RE.match(raw)
        if m:
            return m.group("base").strip(), "（" + m.group(2) + "）"
        m = _SEP_GEO_RE.match(raw)
        if m:
            return m.group("base").strip(), m.group(2)
        return raw, None

    def fn(a, b):
        ba, ta = _parse_branch(a)
        bb, tb = _parse_branch(b)
        if not ba or not bb:
            return None
        if ba == bb and a != b and (ta or tb):
            return ba
        if not ta and bb == a:
            return bb
        if not tb and ba == b:
            return ba
        return None

    def pf(n):
        return _parse_branch(n)

cases_should_merge = [
    ("锐捷网络北京分公司", "锐捷网络上海分公司"),
    ("锐捷网络（北京）", "锐捷网络（上海）"),
    ("锐捷网络", "锐捷网络北京分公司"),
    ("锐捷网络第一分公司", "锐捷网络第二分公司"),
    ("华为技术有限公司深圳分公司", "华为技术有限公司北京分公司"),
    ("阿里巴巴（中国）有限公司-浙江", "阿里巴巴（中国）有限公司-江苏"),
    ("锐捷网络-北京", "锐捷网络-上海"),
]
cases_should_not = [
    ("星网锐捷", "锐捷网络"),
    ("锐捷网络", "锐捷网络科技有限公司"),
    ("腾讯科技", "腾讯云计算"),
    ("北京分公司", "上海分公司"),
    ("锐捷网络", "锐捷网络"),
    ("锐捷软件北京分公司", "锐捷网络上海分公司"),
]

print("=== 应合并（期望非 None）===")
for a, b in cases_should_merge:
    print(f"  {a!r} + {b!r} -> {fn(a, b)!r}")
print("=== 不应合并（期望 None）===")
for a, b in cases_should_not:
    print(f"  {a!r} + {b!r} -> {fn(a, b)!r}")
print("=== 解析抽查 ===")
for n in ["锐捷网络北京分公司", "华为技术有限公司深圳分公司", "锐捷网络（北京）", "锐捷网络"]:
    print(f"  {n!r} -> base={pf(n)[0]!r}, tail={pf(n)[1]!r}")
