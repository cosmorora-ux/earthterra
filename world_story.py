# -*- coding: utf-8 -*-
"""
world_story.py
==============
챕터 화면 '노드 그림'의 처음 내용 : 스토리(1차 기간 · 인트로 · 아웃트로 · 2차 기간 · 사명)와 세계 연표(✶ Timeline), 사이사이 그림 카드.
world.json에 노드 그림이 아직 없을 때 한 번만 채워 넣어요. 그다음부터는 운영진이 '노드 편집'에서 고친 내용이 그대로 남아요.
"""

# 고칠 때마다 올려요 : 운영진이 손대지 않은 예전 기본 스토리는 새 것으로 바뀌어요
STORY_VERSION = 2
# 1판(그림 없는 18장)의 카드 id : 이 구성 그대로면 손대지 않은 것으로 보고 새 판으로 바꿔요
OLD_STORY_IDS = {"s1", "s2", "s3", "s4", "t1", "t2", "t3", "t4", "m1", "m2", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8"}

DEFAULT_GRAPH = {
 "nodes": [
  {
   "id": "i_nexus",
   "kind": "image",
   "label": "넥서스 국공립 아카데미",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/nexus.svg",
   "w": 340,
   "chapter": 0,
   "accent": "violet",
   "x": 40,
   "y": 40
  },
  {
   "id": "s1",
   "kind": "text",
   "label": "1차 기간",
   "tag": "약 14세",
   "title": "",
   "text": "넥서스 국공립 아카데미에 러너 캐릭터 기수가 입학한다.\n세계는 황금기를 맞이하고 있으나, 그 가파른 성장곡선만큼 국가 정세가 위태롭다. 머지않아 전쟁이 발발할 것 같다는 불온한 소문이 도는 까닭인데……. 우리에게는 너무 멀게만 들린다. 다소 낭설만 같고, 갑작스러운 이야기다.\n\n그도 그럴 게, 세계는 단 한 순간도 종전을 선언하지 않았다.\n우리가 누렸던 그간의 안온함은 오랜 휴전에 가까운 평화 협약이었으므로.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "violet",
   "x": 40,
   "y": 380
  },
  {
   "id": "t1",
   "kind": "text",
   "label": "1차 기간 인트로",
   "tag": "약 24세",
   "title": "Timeline",
   "text": "아르카디아 연방은 노바 공화국의 레저넌트에게만 부과되는 강압적이고 과도한 책임이 인권 차별에 해당한다는 입장을 표명한다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 450,
   "y": 40
  },
  {
   "id": "t2",
   "kind": "text",
   "label": "Timeline",
   "tag": "02",
   "title": "",
   "text": "노바 공화국은 위 발화를 허울 좋은 명분으로 주장,\n실상은 산업화로 인해 커져가는 국력을 상대국에서 억제하기 위함이라는 입장을 낸다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 450,
   "y": 250
  },
  {
   "id": "t3",
   "kind": "text",
   "label": "Timeline",
   "tag": "03",
   "title": "",
   "text": "양국 첩보 작전을 펼치며, 노바 공화국은 아르카디아 연방이 ‘레저넌트 중심의 낙원’을 구상하고 있음을 확인한다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 450,
   "y": 440
  },
  {
   "id": "t4",
   "kind": "text",
   "label": "Timeline",
   "tag": "04",
   "title": "",
   "text": "선제적으로 들어온 국제적 압박에, 노바 공화국은 아르카디아 연방을 향해 압도적 무력으로 대응하기 시작한다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 450,
   "y": 630
  },
  {
   "id": "s2",
   "kind": "text",
   "label": "1차 기간 인트로",
   "tag": "약 24세",
   "title": "",
   "text": "졸업 이후 두 국가의 전쟁이 발발한다. 러너원 전원, 소속 국가의 군인으로서 전쟁에 임한다. 그리하여 접경 지역, 두 레저넌트 무리가 조우한다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 450,
   "y": 810
  },
  {
   "id": "i_arcadia",
   "kind": "image",
   "label": "아르카디아 연방",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/arcadia.svg",
   "w": 220,
   "chapter": 0,
   "accent": "amber",
   "x": 860,
   "y": 40
  },
  {
   "id": "i_nova",
   "kind": "image",
   "label": "노바 공화국",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/nova.svg",
   "w": 220,
   "chapter": 0,
   "accent": "blue",
   "x": 860,
   "y": 290
  },
  {
   "id": "s3",
   "kind": "text",
   "label": "1차 기간 아웃트로",
   "tag": "",
   "title": "",
   "text": "전쟁은 지난한 상처를 모두 할퀴고서야 종막을 내린다. 그리고 종전 이후, 기억의 퓨즈. 뺨을 스치는 칼바람이 정신을 깨운다. 우리는 프랙처 토벌대에 차출되어 다음 전쟁을 준비하는 중이다. 아, 비로소 우리는 직감한다. 나 자신마저 죽음으로 잃고 말 때까지 할 수 있는 것은 없다. 이 전쟁은 영원히 끝나지 않을 ■■루프다…….",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "violet",
   "x": 1150,
   "y": 40
  },
  {
   "id": "i_fracture",
   "kind": "image",
   "label": "Fracture",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/fracture.svg",
   "w": 340,
   "chapter": 0,
   "accent": "blue",
   "x": 1150,
   "y": 310
  },
  {
   "id": "s4",
   "kind": "text",
   "label": "2차 기간",
   "tag": "약 24세",
   "title": "",
   "text": "전쟁 발발 직전으로 회귀?\n\n전쟁의 기세는 노바 공화국에 한참 기울었다. 노바 공화국 본국은 물론, 아르카디아 연방 전체에 깔린 전선망은 정보화 사회를 가속화고 더욱 촘촘한 레저넌트의 감시탑으로써 기동한다. 우리는 오랜 기간 바다 저 깊은 심연에서 닻처럼 박혀 때를 기다려 왔다. 이제는 날개를 펼칠 때. 지난한 운명을 매듭 지으라, 루프가 우리를 재촉한다.\n\n주어진 사명은 단 두 가지다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "violet",
   "x": 1560,
   "y": 40
  },
  {
   "id": "m1",
   "kind": "text",
   "label": "Mission 01",
   "tag": "",
   "title": "",
   "text": "우리는 우리의 삶을 위해 -관료제적 통제국가- 노바 공화국을 혁명한다.\n공명자의 또다른 이름은 저항가Resistance다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "red",
   "x": 1970,
   "y": 40
  },
  {
   "id": "m2",
   "kind": "text",
   "label": "Mission 02",
   "tag": "",
   "title": "",
   "text": "우리는 인류의 삶을 위해 -세계의 균열- 프랙처로부터 설원을, 루프를 찬탈한다.\n레저넌트의 또다른 이름은 레버넌트Revenant다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "red",
   "x": 1970,
   "y": 230
  },
  {
   "id": "w1",
   "kind": "text",
   "label": "서력 2100년",
   "tag": "✶ Timeline",
   "title": "인류 문명 붕괴",
   "text": "지구에서 살아남은 인류는 극소수에 불과하다.\n다시, 이들 중에서도 소수의 인류가 루프Loop 입자를 목격.\n이를 이능력자 레저넌트의 탄생으로 일컫는다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 40,
   "y": 1070
  },
  {
   "id": "w2",
   "kind": "text",
   "label": "공력 0~500년",
   "tag": "",
   "title": "공력의 탄생",
   "text": "공력 500년간, 서력 2000년치의 옛 문명이 재건됨.\n\n——보아라. 레저넌트로 말미암아 지구Earth의 황금기가 다시 도래했다.\n공력 0~300년, 다양한 국가간 크고 작은 전쟁이 일어났다.\n공력 300년, 아르카디아 연방과 노바 공화국의 두 국가를 남기고 전 대륙 대통합.\n근 200년간은 평화 휴전이 진행되었다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 450,
   "y": 1070
  },
  {
   "id": "w3",
   "kind": "text",
   "label": "공력 498~500년",
   "tag": "",
   "title": "러너 캐릭터들 탄생",
   "text": "",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 860,
   "y": 1070
  },
  {
   "id": "w4",
   "kind": "text",
   "label": "공력 514년",
   "tag": "",
   "title": "[1차 기간]",
   "text": "아카데미 입학: 중세~근대\n상위 5%의 잠재력을 가진 개체로서 입학되었다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 1270,
   "y": 1070
  },
  {
   "id": "w5",
   "kind": "text",
   "label": "공력 524년",
   "tag": "",
   "title": "[2차 기간]",
   "text": "졸업 직후 전쟁 발발: 근대~현대\n주 무대는 지구의 아르카디아 연방입니다.\n\n——국가의 의무란 국경의 울타리 안 소수의 시민을 수호하는 것이다.\n레저넌트로 징집되어 적국과 교전을 펼침. 「사도」와 「보이드」의 생존을 건 결전.\n\nPVP전투 진행, 패전국은 승전국에 병합됩니다. 패전국 국민은 가족, 고향을 잃을 가능성이 높습니다. 해당 전투로 러너원의 50%가 사망합니다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 1680,
   "y": 1070
  },
  {
   "id": "w6",
   "kind": "text",
   "label": "전쟁 후",
   "tag": "",
   "title": "[SYSTEM ERROR]",
   "text": "1차 기간 최종 생존 인원 한정 약식 레이드를 실시하며, 참여자에게 서사적인 특전이 부여됩니다.\n✶",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 2090,
   "y": 1070
  },
  {
   "id": "w7",
   "kind": "text",
   "label": "공력 524년",
   "tag": "",
   "title": "[3차 기간]",
   "text": "공력 500년에서 갈라진 평행 우주: 현대~근미래\n전쟁 전 시점, 주 무대는 테라의 노바 공화국입니다.\n\n——우리의 삶은 루프로 존재한다. 허나 반복될 것인가, 거역할 것인가.\n이곳은 지구가 아니다. 그 동시에 지구가 분명하다. 진상을 아는 우리만이 이곳을 테라Terra라고 부른다.\n\n——그리고, 그럼에도 죽고 만 자들은 ■■을…….",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 2500,
   "y": 1070
  },
  {
   "id": "w8",
   "kind": "text",
   "label": "ing…….",
   "tag": "",
   "title": "[SYSTEM ■■■■■]",
   "text": "우리가 선택하게 될 엔딩은, ■■다.",
   "image": None,
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 2910,
   "y": 1070
  },
  {
   "id": "i_loop",
   "kind": "image",
   "label": "Loop",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/loop.svg",
   "w": 340,
   "chapter": 0,
   "accent": "amber",
   "x": 40,
   "y": 1300
  },
  {
   "id": "i_terra",
   "kind": "image",
   "label": "Terra",
   "tag": "",
   "title": "",
   "text": "",
   "image": "/static/world_default/terra.svg",
   "w": 340,
   "chapter": 0,
   "accent": "violet",
   "x": 2500,
   "y": 1410
  }
 ],
 "edges": [
  {
   "a": "s1",
   "as": "r",
   "at": 0.5,
   "b": "t1",
   "bs": "l",
   "bt": 0.3
  },
  {
   "a": "t1",
   "as": "b",
   "at": 0.5,
   "b": "t2",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "t2",
   "as": "b",
   "at": 0.5,
   "b": "t3",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "t3",
   "as": "b",
   "at": 0.5,
   "b": "t4",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "t4",
   "as": "b",
   "at": 0.5,
   "b": "s2",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "s3",
   "as": "r",
   "at": 0.5,
   "b": "s4",
   "bs": "l",
   "bt": 0.5
  },
  {
   "a": "s4",
   "as": "r",
   "at": 0.5,
   "b": "m1",
   "bs": "l",
   "bt": 0.4
  },
  {
   "a": "s4",
   "as": "r",
   "at": 0.5,
   "b": "m2",
   "bs": "l",
   "bt": 0.4
  },
  {
   "a": "w1",
   "as": "r",
   "at": 0.25,
   "b": "w2",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w2",
   "as": "r",
   "at": 0.25,
   "b": "w3",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w3",
   "as": "r",
   "at": 0.25,
   "b": "w4",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w4",
   "as": "r",
   "at": 0.25,
   "b": "w5",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w5",
   "as": "r",
   "at": 0.25,
   "b": "w6",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w6",
   "as": "r",
   "at": 0.25,
   "b": "w7",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "w7",
   "as": "r",
   "at": 0.25,
   "b": "w8",
   "bs": "l",
   "bt": 0.25
  },
  {
   "a": "i_nexus",
   "as": "b",
   "at": 0.5,
   "b": "s1",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "s2",
   "as": "r",
   "at": 0.5,
   "b": "i_arcadia",
   "bs": "l",
   "bt": 0.5
  },
  {
   "a": "s2",
   "as": "r",
   "at": 0.5,
   "b": "i_nova",
   "bs": "l",
   "bt": 0.5
  },
  {
   "a": "i_arcadia",
   "as": "r",
   "at": 0.5,
   "b": "s3",
   "bs": "l",
   "bt": 0.35
  },
  {
   "a": "i_nova",
   "as": "r",
   "at": 0.5,
   "b": "s3",
   "bs": "l",
   "bt": 0.65
  },
  {
   "a": "s3",
   "as": "b",
   "at": 0.5,
   "b": "i_fracture",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "w1",
   "as": "b",
   "at": 0.5,
   "b": "i_loop",
   "bs": "t",
   "bt": 0.5
  },
  {
   "a": "w7",
   "as": "b",
   "at": 0.5,
   "b": "i_terra",
   "bs": "t",
   "bt": 0.5
  }
 ]
}
