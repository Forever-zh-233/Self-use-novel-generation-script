"""Migrate ledger.json: resources -> inventory, add new fields."""
import json

LEDGER = r"E:\Novel 1\runtime\ledger.json"

with open(LEDGER, encoding="utf-8") as f:
    ledger = json.load(f)

# Remove old messy resources
if "resources" in ledger:
    del ledger["resources"]

# Add structured inventory
ledger["inventory"] = {
    "consumables": [
        {"name": "银针", "qty": 3, "notes": "一根沾黑灰已拔出归位", "last_chapter": 43},
        {"name": "绿豆", "qty": 0, "notes": "需补充", "last_chapter": 35},
        {"name": "退热散", "qty": 0, "notes": "已用完", "last_chapter": 16}
    ],
    "key_items": [
        {"name": "黄纸", "qty": 3, "location": "鞋垫底下", "acquired_chapter": 5, "status": "持有"},
        {"name": "赵四凿子", "qty": 1, "location": "竹杖暗格", "acquired_chapter": 22, "status": "持有"},
        {"name": "铁片(地道分叉图)", "qty": 1, "location": "随身", "acquired_chapter": 40, "status": "持有"},
        {"name": "窑场木牌", "qty": 1, "location": "随身", "acquired_chapter": 41, "status": "持有"},
        {"name": "碎瓷片(血字窑井)", "qty": 1, "location": "随身", "acquired_chapter": 42, "status": "持有"},
        {"name": "刻字布条", "qty": 1, "location": "药箱夹层", "acquired_chapter": 29, "status": "持有"},
        {"name": "烧焦黄纸残片", "qty": 1, "location": "针包底下", "acquired_chapter": 18, "status": "持有"},
        {"name": "通行令(巡夜司铜牌)", "qty": 1, "location": "腰带", "acquired_chapter": 7, "status": "持有"}
    ],
    "techniques": [
        {"name": "退热散配方", "type": "医术", "realm": "凡人", "source": "了愿奖励", "chapter": 1},
        {"name": "朱砂解毒针法残页", "type": "针法", "realm": "叩门", "source": "了愿奖励", "chapter": 19},
        {"name": "追踪术入门残页", "type": "术法", "realm": "叩门", "source": "了愿奖励", "chapter": 19, "status": "可修炼未习得"}
    ],
    "currency": {
        "银两": 5,
        "铜钱": 8,
        "notes": "周通付5两;住店花8文;茶水2文;原16文余8文"
    }
}

# Add 了愿 log
ledger["liaoYuan_log"] = [
    {"chapter": 1, "wish": "张寡妇孩子退烧", "who": "张寡妇", "reward": "退热散配方+寿命1年", "level_after": "LV1(1/10)"},
    {"chapter": 15, "wish": "陈二嫂朱砂中毒解救", "who": "陈二嫂", "reward": "寿命+2年+朱砂解毒针法残页+追踪术入门残页", "level_after": "LV1(4/10)"},
    {"chapter": 19, "wish": "连续了愿累计触发阶段性奖励", "who": "系统", "reward": "寿命+2年(累计66年)", "level_after": "LV1(4/10)"}
]

# Add motifs
ledger["motifs"] = [
    {"symbol": "黑线", "meaning": "朱砂侵蚀/死亡倒计时", "first_chapter": 5, "last_chapter": 43, "count": 15, "evolution": ["手腕标记", "蔓延到肘部", "嗡鸣与左眼刺痛同步"]},
    {"symbol": "竹杖", "meaning": "沈安身份标识/感知工具/暗格武器", "first_chapter": 1, "last_chapter": 43, "count": 40, "evolution": ["拐杖", "暗格藏凿子", "探路工具"]},
    {"symbol": "朱砂红光", "meaning": "危险/邪术/死亡", "first_chapter": 8, "last_chapter": 43, "count": 20, "evolution": ["路引标记", "井壁荧光", "棺材内壁", "黑线共鸣源"]},
    {"symbol": "磨刀声", "meaning": "棺材铺秘密/刻纹仪式", "first_chapter": 23, "last_chapter": 29, "count": 6, "evolution": ["铺主刻棺材", "不明人继续刻"]},
    {"symbol": "三道刻痕(断第三笔)", "meaning": "未知符号/跨物件一致", "first_chapter": 20, "last_chapter": 35, "count": 8, "evolution": ["黄纸背面", "铁链上", "门槛上", "布条上"]}
]

with open(LEDGER, "w", encoding="utf-8") as f:
    json.dump(ledger, f, ensure_ascii=False, indent=2)

print(f"OK - ledger migrated. Keys: {list(ledger.keys())}")
print(f"Inventory: {len(ledger['inventory']['consumables'])} consumables, {len(ledger['inventory']['key_items'])} key_items, {len(ledger['inventory']['techniques'])} techniques")
print(f"liaoYuan_log: {len(ledger['liaoYuan_log'])} entries")
print(f"motifs: {len(ledger['motifs'])} entries")
