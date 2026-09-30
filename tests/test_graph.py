"""app.graph 纯算法测试：传递推导、矛盾检测、路径择优。"""
from app import graph


def A(eid, kind, a, b):
    return graph.Assertion(eid, kind, a, b)


def test_same_transitive():
    data = [A("e1", "same", "a", "b"), A("e2", "same", "b", "c")]
    assert graph.query_relation(data, "a", "c")["relation"] == "same"
    assert graph.find_contradiction(data) is None


def test_same_is_symmetric():
    data = [A("e1", "same", "a", "b")]
    assert graph.query_relation(data, "b", "a")["relation"] == "same"


def test_before_path_through_same_chain():
    data = [
        A("e1", "same", "b", "c"),
        A("e2", "same", "c", "d"),
        A("e3", "before", "a", "b"),
        A("e4", "before", "d", "e"),
    ]
    r = graph.query_relation(data, "a", "e")
    assert r["relation"] == "before"
    assert r["evidence_path"] == ["e3", "e1", "e2", "e4"]
    r2 = graph.query_relation(data, "e", "a")
    assert r2["relation"] == "after"
    assert graph.find_contradiction(data) is None


def test_unknown_when_no_path():
    data = [A("e1", "before", "a", "b")]
    assert graph.query_relation(data, "a", "x")["relation"] == "unknown"
    assert graph.query_relation(data, "a", "b")["relation"] == "before"


def test_intra_group_before_direct_same():
    data = [A("e1", "same", "a", "b"), A("e2", "before", "a", "b")]
    c = graph.find_contradiction(data)
    assert c["type"] == "intra_group"
    assert set(c["evidence_path"]) == {"e1", "e2"}


def test_intra_group_before_via_same_chain():
    data = [
        A("e1", "same", "a", "b"),
        A("e2", "same", "b", "c"),
        A("e3", "before", "c", "a"),
    ]
    c = graph.find_contradiction(data)
    assert c["type"] == "intra_group"
    assert c["evidence_path"][-1] == "e3"
    assert set(c["evidence_path"]) == {"e1", "e2", "e3"}


def test_simple_before_cycle():
    data = [
        A("e1", "before", "a", "b"),
        A("e2", "before", "b", "c"),
        A("e3", "before", "c", "a"),
    ]
    c = graph.find_contradiction(data)
    assert c["type"] == "cycle"
    assert c["evidence_path"].count("e1") == 1
    assert set(c["evidence_path"]) == {"e1", "e2", "e3"}


def test_cycle_on_class_quotient_graph():
    # A~B, C~D；A<C, C<B? 等价类边 X->Y, Y->X 成环
    data = [
        A("s1", "same", "A", "B"),
        A("s2", "same", "C", "D"),
        A("e1", "before", "A", "C"),
        A("e2", "before", "D", "B"),
    ]
    c = graph.find_contradiction(data)
    assert c["type"] == "cycle"
    assert set(c["evidence_path"]) >= {"e1", "e2"}
    # 展开的地层路径以同一期桥接
    assert "s1" in c["evidence_path"] or "s2" in c["evidence_path"]


def test_chain_is_not_cycle():
    data = [
        A("e1", "before", "a", "b"),
        A("e2", "before", "b", "c"),
        A("e3", "before", "c", "d"),
    ]
    assert graph.find_contradiction(data) is None
    assert graph.query_relation(data, "a", "d")["relation"] == "before"
    assert graph.query_relation(data, "d", "a")["relation"] == "after"


def test_self_before_is_intra_group():
    data = [A("e1", "before", "a", "a")]
    c = graph.find_contradiction(data)
    assert c["type"] == "intra_group"
    assert c["evidence_path"] == ["e1"]


def test_path_prefers_fewer_evidences_then_lexicographic():
    # 直接长边 e-z 与两条短边链路；边数优先
    data = [
        A("z", "before", "a", "c"),      # 1 条证据
        A("a", "before", "a", "b"),
        A("b", "before", "b", "c"),      # 2 条证据
    ]
    r = graph.query_relation(data, "a", "c")
    assert r["evidence_path"] == ["z"]

    # 两条长度相同：选字典序更小的证据链
    data2 = [
        A("a9", "before", "a", "m"),
        A("a1", "before", "a", "n"),
        A("z9", "before", "m", "c"),
        # n->c 用 a2，使 [a1, a2] < [a9, z9]
        A("a2", "before", "n", "c"),
    ]
    r2 = graph.query_relation(data2, "a", "c")
    assert r2["evidence_path"] == ["a1", "a2"]


def test_withdraw_resolves_conflict():
    # 撤回闭环上的一条边后恢复一致
    data_all = [
        A("e1", "before", "a", "b"),
        A("e2", "before", "b", "c"),
        A("e3", "before", "c", "a"),
    ]
    assert graph.find_contradiction(data_all)["type"] == "cycle"
    data_left = [x for x in data_all if x.evidence_id != "e3"]
    assert graph.find_contradiction(data_left) is None
    assert graph.query_relation(data_left, "a", "c")["relation"] == "before"


def test_same_path_lexicographic():
    data = [
        A("zzz", "same", "a", "b"),
        A("aaa", "same", "a", "c"),
        A("mmm", "same", "c", "b"),
    ]
    r = graph.query_relation(data, "a", "b")
    assert r["relation"] == "same"
    assert r["evidence_path"] == ["zzz"]  # 1 跳优于 2 跳
