"""纯函数核心：地层关系图的推导、矛盾检测与最优证据路径选择。

规则
----
* SAME（同一期）：无向边，可传递、可交换（a 同一期 b ⇒ b 同一期 a）。
* BEFORE（早于）：有向边。沿「早于」与「同一期」路径推导，即
  a 早于 b ⇔ 有向图（SAME 边双向、BEFORE 边单向）存在 a→b 的路径。
* 矛盾有两类：
  1. 组内早于：同一条 SAME 等价类内出现 BEFORE 边；
  2. 早于闭环：把 SAME 等价类收缩为节点后，BEFORE 边形成有向环。
* 路径择优：先取证据数最少（边数最少），再取证据编号元组字典序最小。

证据编号全局唯一（由持久层保证），因此贪心选取当前层最小证据编号即可得到
字典序最小的最短路径。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

SAME = "same"
BEFORE = "before"


@dataclass(frozen=True)
class Assertion:
    evidence_id: str
    kind: str
    a: str
    b: str


class _DSU:
    def __init__(self, nodes):
        self.parent = {n: n for n in nodes}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # 以成员中最小编号作为规范代表，保证结果确定性
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def _shortest_path(adj, start, goal):
    """在有向图 adj（node -> {neighbor: [evidence_id, ...]}）中求 start→goal。

    返回 (边数, 证据编号元组, 节点元组)；不可达返回 None。
    边数最少；并列时证据编号元组字典序最小。
    start == goal 返回 (0, (), (start,))。
    """
    if start == goal:
        return 0, (), (start,)
    if start not in adj or goal not in adj:
        return None

    # 反向 BFS：每个节点到 goal 的最短距离
    rev = defaultdict(list)
    for u, nbrs in adj.items():
        for v in nbrs:
            rev[v].append(u)
    dist = {goal: 0}
    frontier = [goal]
    while frontier:
        nxt = []
        for u in frontier:
            for w in rev[u]:
                if w not in dist:
                    dist[w] = dist[u] + 1
                    nxt.append(w)
        frontier = nxt
    if start not in dist:
        return None

    # 正向贪心重建：每一步都走「仍在最短路上」且证据编号最小的边
    eids, nodes = [], [start]
    u = start
    while u != goal:
        best = None  # (evidence_id, neighbor)
        for v, es in adj[u].items():
            if dist.get(v) == dist[u] - 1:
                for e in es:
                    cand = (e, v)
                    if best is None or cand < best:
                        best = cand
        e, v = best
        eids.append(e)
        nodes.append(v)
        u = v
    return dist[start], tuple(eids), tuple(nodes)


@dataclass
class _Graph:
    nodes: set
    same_adj: dict       # 无向：node -> {neighbor: [eid]}
    dir_adj: dict        # 有向（SAME 双向 + BEFORE 单向）：node -> {neighbor: [eid]}
    dsu: _DSU
    befores: list        # [(a, b, eid)]


def _build(assertions) -> _Graph:
    nodes = set()
    for x in assertions:
        nodes.add(x.a)
        nodes.add(x.b)

    same_adj = {n: defaultdict(list) for n in nodes}
    dir_adj = {n: defaultdict(list) for n in nodes}
    befores = []
    dsu = _DSU(nodes)

    for x in assertions:
        if x.kind == SAME:
            dsu.union(x.a, x.b)
            same_adj[x.a][x.b].append(x.evidence_id)
            same_adj[x.b][x.a].append(x.evidence_id)
            dir_adj[x.a][x.b].append(x.evidence_id)
            dir_adj[x.b][x.a].append(x.evidence_id)
        else:
            befores.append((x.a, x.b, x.evidence_id))
            dir_adj[x.a][x.b].append(x.evidence_id)

    return _Graph(nodes, same_adj, dir_adj, dsu, befores)


def find_contradiction(assertions) -> Optional[dict]:
    """核验整批关系。无矛盾返回 None；有矛盾返回冲突路径描述。"""
    g = _build(assertions)

    # ---- 1. 组内早于（含 a 早于 a 自环）----
    intra = []
    for a, b, e in g.befores:
        if g.dsu.find(a) == g.dsu.find(b):
            intra.append((e, a, b))
    if intra:
        e, a, b = min(intra)  # 结果确定性：取证据编号最小者
        if a == b:
            return {
                "type": "intra_group",
                "message": f"地层 {a} 与自身处于同一期，却存在「早于」断言（证据 {e}）",
                "evidence_path": [e],
                "stratum_path": [a, a],
            }
        sp = _shortest_path(g.same_adj, a, b)
        same_eids = list(sp[1])
        same_nodes = list(sp[2])
        return {
            "type": "intra_group",
            "message": (
                f"组内早于：{a} 与 {b} 经同一期链 {same_eids} 等价，"
                f"但证据 {e} 断言 {a} 早于 {b}"
            ),
            "evidence_path": same_eids + [e],
            # a ~...~ b（同一期链），再由 BEFORE 边 b←a 闭环
            "stratum_path": same_nodes + [a],
        }

    # ---- 2. 等价类商图上的有向环 ----
    # class_adj[C1][C2] = 该类间最小证据编号的 BEFORE 断言 (eid, a, b)
    class_adj = defaultdict(dict)
    for a, b, e in g.befores:
        ca, cb = g.dsu.find(a), g.dsu.find(b)
        old = class_adj[ca].get(cb)
        if old is None or e < old[0]:
            class_adj[ca][cb] = (e, a, b)

    classes = {g.dsu.find(n) for n in g.nodes}
    color = {c: 0 for c in classes}  # 0 未访问 / 1 在栈中 / 2 已完成
    came_from = {}

    def reconstruct(cycle_classes, edges):
        """把类级环展开为地层级证据路径。

        cycle_classes = [C0, C1, ..., C{k-1}]，
        edges[i] = (eid, ai, bi) 为 Ci -> C{i+1}（i 取模 k）的代表边。
        """
        evidence_path, stratum_path = [], [edges[0][1]]
        for i, (e, a, b) in enumerate(edges):
            evidence_path.append(e)
            stratum_path.append(b)
            if i + 1 < len(edges):
                next_a = edges[i + 1][1]
            else:
                next_a = edges[0][1]  # 回到环起点的起始地层
            if b != next_a:
                sp = _shortest_path(g.same_adj, b, next_a)
                evidence_path.extend(sp[1])
                stratum_path.extend(sp[2][1:])
        return evidence_path, stratum_path

    for start in sorted(classes):
        if color[start] != 0:
            continue
        color[start] = 1
        stack = [(start, iter(sorted(class_adj[start])))]
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                color[u] = 2
                stack.pop()
                continue
            edge = class_adj[u][v]
            if color[v] == 0:
                color[v] = 1
                came_from[v] = (u, edge)
                stack.append((v, iter(sorted(class_adj[v]))))
            elif color[v] == 1:
                # 回边 u -> v，环为 v → ... → u → v
                chain = [u]
                edge_chain = [edge]
                while chain[-1] != v:
                    prev, pedge = came_from[chain[-1]]
                    chain.append(prev)
                    edge_chain.append(pedge)
                chain.reverse()          # C0=v ... C{k-1}=u
                edge_chain.reverse()     # edges[i]: Ci -> C{i+1}
                evidence_path, stratum_path = reconstruct(chain, edge_chain)
                return {
                    "type": "cycle",
                    "message": (
                        "早于闭环：等价类 "
                        + " -> ".join(chain)
                        + f" -> {chain[0]}，证据链 {evidence_path}"
                    ),
                    "evidence_path": evidence_path,
                    "stratum_path": stratum_path,
                    "class_path": chain + [chain[0]],
                }
    return None


def query_relation(assertions, a: str, b: str) -> dict:
    """查询两地层关系，返回 relation 与支撑证据路径。"""
    g = _build(assertions)
    if a not in g.nodes or b not in g.nodes:
        return {"relation": "unknown", "evidence_path": [], "stratum_path": []}

    same_sp = _shortest_path(g.same_adj, a, b)
    if same_sp is not None:
        return {
            "relation": SAME,
            "evidence_path": list(same_sp[1]),
            "stratum_path": list(same_sp[2]),
        }

    fwd = _shortest_path(g.dir_adj, a, b)
    if fwd is not None:
        return {
            "relation": BEFORE,
            "evidence_path": list(fwd[1]),
            "stratum_path": list(fwd[2]),
        }

    back = _shortest_path(g.dir_adj, b, a)
    if back is not None:
        # b 早于 a ⇒ a 晚于 b；证据路径仍按查询方向 a→b 展示
        return {
            "relation": "after",
            "evidence_path": list(back[1]),
            "stratum_path": list(reversed(back[2])),
        }

    return {"relation": "unknown", "evidence_path": [], "stratum_path": []}
