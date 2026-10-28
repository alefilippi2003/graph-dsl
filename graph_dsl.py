from __future__ import annotations
from dataclasses import dataclass
from typing import Set, Tuple, Callable, Union
from lark import Lark, Token, Tree
from collections import deque
import os
import networkx as nx
import matplotlib.pyplot as plt

# --- DOMINIO SEMANTICO ---

@dataclass
class Graph:
    nodes: Set[str]
    edges: Set[Tuple[str, str]] 

@dataclass(frozen=True)
class Loc:
    address: int

EVal = Union[Graph, int, bool]
MVal = EVal 
@dataclass
class Closure:
    function: FunctionDecl
    env: Environment  
    
DVal = Union[EVal, Loc, Callable, Closure]

Environment = Callable[[str], DVal]

@dataclass
class State:
    store: Callable[[int], MVal]
    next_loc: int

# --- FUNZIONI PRIMITIVE PER STATO E AMBIENTE ---

def empty_store() -> Callable[[int], MVal]:
    def store_fn(loc: int) -> MVal:
        raise ValueError(f"Locazione {loc} non allocata")
    return store_fn

def empty_state() -> State:
    return State(store=empty_store(), next_loc=0)

def allocate(state: State, value: MVal) -> tuple[Loc, State]:
    """Crea una nuova locazione, vi memorizza il valore e aggiorna lo stato."""
    loc = Loc(state.next_loc)
    prev_store = state.store
    def new_store(l: int) -> MVal:
        if l == loc.address: return value
        return prev_store(l)
    return loc, State(store=new_store, next_loc=loc.address + 1)

def update(state: State, addr: int, value: MVal) -> State:
    """Aggiorna il valore in una locazione esistente."""
    prev_store = state.store
    def new_store(l: int) -> MVal:
        if l == addr: return value
        return prev_store(l)
    return State(store=new_store, next_loc=state.next_loc)

def access(state: State, addr: int) -> MVal:
    """Legge il valore in una locazione."""
    return state.store(addr)

# --- GRAMMATICA LARK ---

grammar = r"""
    ?start: command_seq

    ?command_seq: command
               | command ";" command_seq

    ?command: assign
            | print_stmt
            | plot_stmt
            | vardecl
            | ifelse
            | while
            | fundecl

    assign: IDENTIFIER "<-" expr
    print_stmt: "PRINT" expr
    plot_stmt: "PLOT" expr
    vardecl: "var" IDENTIFIER "=" expr
    ifelse: "IF" expr "THEN" command_seq "ELSE" command_seq "ENDIF"
    while: "WHILE" expr "DO" command_seq "DONE"
    fundecl: "DEF" IDENTIFIER "(" param_list ")" "=" expr
    param_list: IDENTIFIER ("," IDENTIFIER)*

    ?expr: binary_op
         | glue_op
         | path_op
         | mono

    ?mono: graph_lit
         | var
         | ground
         | "(" expr ")"
         | funapp

    graph_lit: "{" [graph_content] "}"
    graph_content: item ("," item)*
    item: edge | node_def
    edge: IDENTIFIER "-" IDENTIFIER 
    node_def: IDENTIFIER

    ground: NUMBER | BOOL
    BOOL: "true" | "false"
    NUMBER: /[0-9]+/

    binary_op: expr OP mono
    
    OP: "UNIONE" | "INTERSEZIONE" | "==" | "!=" | "<" | ">" | "<=" | ">=" | "AND" | "OR" | "+" | "-" | "*" | "/"

    glue_op: "INCOLLA" "(" expr "," expr "," IDENTIFIER "," IDENTIFIER ")"
    path_op: "DISTANZA" "(" expr "," IDENTIFIER "," IDENTIFIER ")"
    
    funapp: IDENTIFIER "(" arg_list ")"
    arg_list: expr ("," expr)*

    var: IDENTIFIER
    IDENTIFIER: /[a-zA-Z_][a-zA-Z0-9_]*/

    %import common.WS
    %ignore WS
"""

parser = Lark(grammar, start="start")

# --- IMPLEMENTAZIONE SEMANTICA ---

def union(G1: Graph, G2: Graph) -> Graph:
    return Graph(nodes=G1.nodes.union(G2.nodes), edges=G1.edges.union(G2.edges))

def intersect(G1: Graph, G2: Graph) -> Graph:
    return Graph(nodes=G1.nodes.intersection(G2.nodes), edges=G1.edges.intersection(G2.edges))

def glue(G1: Graph, G2: Graph, N1: str, N2: str) -> Graph:
    """Unisce due grafi identificando N1 con N2. Rinomina gli altri nodi per evitare collisioni."""
    if N1 not in G1.nodes: raise ValueError(f"Nodo {N1} mancante in G1")
    if N2 not in G2.nodes: raise ValueError(f"Nodo {N2} mancante in G2")
    
    merged_id = f"{N1}_{N2}" 

    map_1 = {n: (merged_id if n == N1 else f"{n}_1") for n in G1.nodes}
    nodes_1 = set(map_1.values())
    edges_1 = {(map_1[u], map_1[v]) for u, v in G1.edges}
    
    map_2 = {n: (merged_id if n == N2 else f"{n}_2") for n in G2.nodes}
    nodes_2 = set(map_2.values())
    edges_2 = {(map_2[u], map_2[v]) for u, v in G2.edges}

    return Graph(nodes=nodes_1.union(nodes_2), edges=edges_1.union(edges_2))

def short_path(G: Graph, N1: str, N2: str) -> int:
    """Calcola la distanza minima usando BFS."""
    missing = {N1, N2} - G.nodes
    if missing: raise ValueError(f"Nodi mancanti: {missing}")
    if N1 == N2: return 0

    adj = {node: [] for node in G.nodes}
    for u, v in G.edges:
        adj[u].append(v)
        adj[v].append(u)

    queue = deque([(N1, 0)])
    visited = {N1}

    while queue:
        current, dist = queue.popleft()
        if current == N2: return dist

        for neighbor in adj[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))

    raise ValueError(f"Nessun percorso tra {N1} e {N2}")

# --- AMBIENTE FUNZIONALE ---

def empty_environment() -> Environment:
    def env(name: str) -> DVal:
        raise ValueError(f"Identificatore non definito: {name}")
    return env

def lookup(env: Environment, name: str) -> DVal:
    return env(name)

def bind(env: Environment, name: str, value: DVal) -> Environment:
    def new_env(n: str) -> DVal:
        if n == name: return value
        return env(n)
    return new_env
def create_initial_env_state() -> tuple[Environment, State]:
    env = empty_environment()
    state = empty_state()
    
    env = bind(env, "UNIONE", union)
    env = bind(env, "INTERSEZIONE", intersect)
    env = bind(env, "INCOLLA", glue)
    env = bind(env, "DISTANZA", short_path)
    env = bind(env, "==", lambda a, b: a == b)
    env = bind(env, "!=", lambda a, b: a != b)
    env = bind(env, ">", lambda a, b: a > b)
    env = bind(env, "<", lambda a, b: a < b)
    env = bind(env, ">=", lambda a, b: a >= b)
    env = bind(env, "<=", lambda a, b: a <= b)
    env = bind(env, "AND", lambda a, b: a and b)
    env = bind(env, "OR", lambda a, b: a or b)
    env = bind(env, "+", lambda a, b: a + b)
    env = bind(env, "-", lambda a, b: a - b)
    env = bind(env, "*", lambda a, b: a * b)
    env = bind(env, "/", lambda a, b: a // b) 
    
    return env, state

# --- AST DATACLASSES ---

@dataclass
class Number: value: int
@dataclass
class Bool: value: bool
@dataclass
class Var: name: str
@dataclass
class GraphLiteral: value: Graph
@dataclass
class Apply: 
    op: str
    args: list[Expression]
@dataclass
class FunctionApp:
    name: str
    args: list[Expression]
@dataclass
class StringLit:
    value: str

Expression = Union[Number, Bool, Var, GraphLiteral, Apply, FunctionApp, StringLit]
# --- COMANDI (Azioni che cambiano lo Stato) ---
@dataclass
class VarDecl: 
    name: str
    expr: Expression
@dataclass
class Assign: 
    name: str
    expr: Expression
@dataclass
class Print: 
    expr: Expression
@dataclass
class Plot: 
    expr: Expression
@dataclass
class IfElse: 
    cond: Expression
    then_branch: 'CommandSequence'
    else_branch: 'CommandSequence'
@dataclass
class While:
    cond: Expression
    body: 'CommandSequence'
@dataclass
class FunctionDecl: 
    name: str
    params: list[str]
    body: Expression

@dataclass
class CommandSequence:
    first: 'Command'
    rest: Union['CommandSequence', None] = None

Command = Union[VarDecl, Assign, Print, Plot, IfElse, While, FunctionDecl]

# --- PARSING E TRASFORMAZIONE ---

def transform_expr(tree: Tree) -> Expression:
    match tree:
        case Tree(data="ground", children=[Token(type="NUMBER", value=v)]):
            return Number(int(v))
        case Tree(data="ground", children=[Token(type="BOOL", value=v)]):
            return Bool(True if v == "true" else False)
        case Tree(data="var", children=[Token(value=name)]):
            return Var(name)
        case Tree(data="graph_lit", children=children):
            if not children: return GraphLiteral(Graph(set(), set()))
            nodes, edges = set(), set()
            for item in children[0].children:
                el = item.children[0]
                if el.data == "edge":
                    u, v = el.children[0].value, el.children[1].value
                    nodes.update({u, v})
                    edges.add((u, v))
                elif el.data == "node_def":
                    nodes.add(el.children[0].value)
            return GraphLiteral(Graph(nodes, edges))
        case Tree(data="binary_op", children=[left, Token(value=op), right]):
            return Apply(op, [transform_expr(left), transform_expr(right)])
        case Tree(data="path_op", children=[g, Token(value=n1), Token(value=n2)]):
            return Apply("DISTANZA", [transform_expr(g), Var(n1), Var(n2)])
        case Tree(data="glue_op", children=[g1, g2, Token(value=n1), Token(value=n2)]):
            return Apply("INCOLLA", [transform_expr(g1), transform_expr(g2), Var(n1), Var(n2)])
        case Tree(data="funapp", children=[Token(value=name), args]):
            arg_list = [transform_expr(c) for c in args.children]
            return FunctionApp(name, arg_list)
        case _: raise ValueError(f"Espressione non riconosciuta: {tree.data}")

def transform_command(tree: Tree) -> Command:
    match tree:
        case Tree(data="vardecl", children=[Token(value=name), expr]):
            return VarDecl(name, transform_expr(expr))
        case Tree(data="assign", children=[Token(value=name), expr]):
            return Assign(name, transform_expr(expr))
        case Tree(data="print_stmt", children=[expr]):
            return Print(transform_expr(expr))
        case Tree(data="plot_stmt", children=[expr]):
            return Plot(transform_expr(expr))
        case Tree(data="ifelse", children=[cond, then_b, else_b]):
            return IfElse(transform_expr(cond), transform_seq(then_b), transform_seq(else_b))
        case Tree(data="while", children=[cond, body]):
            return While(transform_expr(cond), transform_seq(body))
        case Tree(data="fundecl", children=[Token(value=name), params, body]):
            p_list = [t.value for t in params.children]
            return FunctionDecl(name, p_list, transform_expr(body))
        case _: raise ValueError(f"Comando non riconosciuto: {tree.data}")

def transform_seq(tree: Tree) -> CommandSequence:
    if tree.data == "command_seq":
        first = transform_command(tree.children[0])
        rest = transform_seq(tree.children[1]) if len(tree.children) > 1 else None
        return CommandSequence(first, rest)
    return CommandSequence(transform_command(tree))
def parse(source_code: str) -> Program:
    return transform_parse_tree(parser.parse(source_code))

# --- VALUTAZIONE ---

def evaluate_expr(expr: Expression, env: Environment, state: State) -> EVal:
    match expr:
        case Number(v): return v
        case Bool(v): return v
        case GraphLiteral(v): return v
        case StringLit(v): return v
        
        case Var(name):
            try:
                dval = lookup(env, name)
                match dval:
                    case Loc(address=addr):
                        return access(state, addr)
                    case _ if isinstance(dval, (int, bool, Graph, str)):
                        return dval
                    case _:
                        return name 
            except ValueError:
                return name
                
        case Apply(op_name, args):
            arg_vals = [evaluate_expr(a, env, state) for a in args]
            op_fn = lookup(env, op_name)
            
            if callable(op_fn):
                return op_fn(*arg_vals)
            raise ValueError(f"'{op_name}' non è un operatore valido")
            
        case FunctionApp(name, args):
            dval = lookup(env, name)
            
            if isinstance(dval, Closure):
                closure = dval
                if len(args) != len(closure.function.params):
                    raise ValueError(f"La funzione {name} richiede {len(closure.function.params)} argomenti")
                
                arg_vals = [evaluate_expr(a, env, state) for a in args]
                
                local_env = closure.env
                for param, val in zip(closure.function.params, arg_vals):
                    local_env = bind(local_env, param, val)
                
                return evaluate_expr(closure.function.body, local_env, state)
            
            elif callable(dval):
                arg_vals = [evaluate_expr(a, env, state) for a in args]
                return dval(*arg_vals)
            
            raise ValueError(f"'{name}' non è una funzione")

def evaluate_stmt(stmt: Statement, env: Environment) -> Environment:
    match stmt:
        case Assign(name, expr):
            return bind(env, name, evaluate_expr(expr, env))
        case Print(expr):
            print(f"OUTPUT >> {evaluate_expr(expr, env)}")
            return env
        case _: raise ValueError(f"Statement ignoto: {stmt}")

def execute_command(cmd: Command, env: Environment, state: State) -> tuple[Environment, State]:
    match cmd:
        case VarDecl(name, expr):
            val = evaluate_expr(expr, env, state)
            loc, new_state = allocate(state, val)
            new_env = bind(env, name, loc)
            return new_env, new_state
            
        case Assign(name, expr):
            try:
                dval = lookup(env, name)
                if isinstance(dval, Loc):
                    val = evaluate_expr(expr, env, state)
                    new_state = update(state, dval.address, val)
                    return env, new_state
                raise ValueError(f"Il target '{name}' non è una variabile assegnabile")
            except ValueError:
                raise ValueError(f"Assegnazione a variabile non dichiarata: '{name}'")
                
        case Print(expr):
            val = evaluate_expr(expr, env, state)
            print(f"OUTPUT >> {val}")
            return env, state

        case Plot(expr): 
            val = evaluate_expr(expr, env, state)
            if isinstance(val, Graph):
                nx_graph = nx.Graph()
                nx_graph.add_nodes_from(val.nodes)
                nx_graph.add_edges_from(val.edges)
                
                plt.figure(figsize=(6, 4))
                nx.draw(nx_graph, with_labels=True, node_color='lightblue', 
                        node_size=800, font_weight='bold', font_color='black', 
                        edge_color='gray')
                plt.title("Visualizzazione Grafo DSL")
                plt.show() 
            else:
                print(f"ERRORE PLOT: '{val}' non è un grafo visualizzabile.")
            return env, state
        case IfElse(cond, then_branch, else_branch):
            cond_val = evaluate_expr(cond, env, state)
            if not isinstance(cond_val, bool): 
                raise ValueError("La condizione IF deve essere booleana")
            
            saved_next_loc = state.next_loc 
            
            if cond_val:
                _, state1 = execute_seq(then_branch, env, state)
            else:
                _, state1 = execute_seq(else_branch, env, state)
                
            state2 = State(store=state1.store, next_loc=saved_next_loc)
            return env, state2
            
        case While(cond, body):
            def rec_fn(curr_env, curr_state):
                cond_val = evaluate_expr(cond, curr_env, curr_state)
                if not isinstance(cond_val, bool): 
                    raise ValueError("La condizione WHILE deve essere booleana")
                
                if cond_val:
                    saved_next_loc = curr_state.next_loc
                    _, state1 = execute_seq(body, curr_env, curr_state)
                    state2 = State(store=state1.store, next_loc=saved_next_loc)
                    return rec_fn(curr_env, state2)
                else:
                    return curr_env, curr_state
                    
            return rec_fn(env, state)
            
        case FunctionDecl(name, params, body):
            closure = Closure(function=cmd, env=env)
            new_env = bind(env, name, closure)
            return new_env, state

def execute_seq(seq: CommandSequence, env: Environment, state: State) -> tuple[Environment, State]:
    env1, state1 = execute_command(seq.first, env, state)
    if seq.rest:
        return execute_seq(seq.rest, env1, state1)
    return env1, state1


def print_help():
    print("""
===========================================================
   🤖  GRAPH DSL - MANUALE COMANDI (Versione Finale)
===========================================================
1. VARIABILI E MEMORIA:
   var G = {A-B}         -> DICHIARA un nuovo grafo
   G <- {A-B, B-C}       -> AGGIORNA un grafo esistente

2. OPERAZIONI:
   UNIONE(G1, G2)        -> Unisce due grafi
   INTERSEZIONE(G1, G2)  -> Trova la parte comune
   INCOLLA(G1, G2, U, V) -> Fonde G1 e G2 unendo U e V
   DISTANZA(G, A, B)     -> Distanza minima tra A e B

3. CONTROLLO DI FLUSSO:
   IF cond THEN ... ELSE ... ENDIF
   WHILE cond DO ... DONE

4. OUTPUT:
   PRINT expr            -> Stampa come testo
   PLOT expr             -> Disegna il grafo a schermo

5. SISTEMA:
   help                  -> Mostra questo menu
   exit                  -> Chiude il programma
===========================================================
    """)

# --- REPL (Read-Eval-Print Loop) ---

def REPL():
    print("--- Graph DSL Interpreter (Scrivi 'help' per il manuale, 'exit' per uscire) ---")
    
    env, state = create_initial_env_state()
    
    while True:
        try:
            text = input("GrafoDSL> ").strip()
            if not text: continue
            
            if text.lower() == "exit": break
            if text.lower() == "help":
                print_help()
                continue  
            
            env, state = execute_seq(ast, env, state)
                
        except Exception as e:
            print(f"ERRORE: {e}")

def parse(source_code: str) -> CommandSequence:
    tree = parser.parse(source_code)
    return transform_seq(tree)

def run_tests():
    print("=== AVVIO TEST CASE ===")
    
    test_programs = [
        (
            "Test 1: Assegnazione e Matematica base",
            """
            var x = 10;
            var y = 5;
            x <- x + y;
            PRINT x
            """
        ),
        (
            "Test 2: Creazione e manipolazione Grafi",
            """
            var G1 = {A-B};
            var G2 = {B-C};
            var G3 = UNIONE(G1, G2);
            PRINT G3
            """
        ),
        (
            "Test 3: Condizionale IF-ELSE con booleani e operatori relazionali",
            """
            var x = 5;
            IF x > 3 THEN
                PRINT {SUCCESSO-SI}
            ELSE
                PRINT {ERRORE_NO}
            ENDIF
            """
        ),
        (
            "Test 4: Ciclo WHILE e Scoping della memoria",
            """
            var n = 3;
            WHILE n > 0 DO
                PRINT n;
                n <- n - 1
            DONE;
            PRINT {FINE-CICLO}
            """
        ),
        (
            "Test 5: Operazioni avanzate sui grafi nel flusso (Distanza)",
            """
            var labirinto = {A-B, B-C, C-D};
            var dist = DISTANZA(labirinto, A, D);
            IF dist == 3 THEN
                PRINT {DISTANZA_CORRETTA}
            ELSE
                PRINT {ERRORE}
            ENDIF
            """
        ),
        (
            "Test 6: Visualizzazione Grafica",
            """
            var G1 = {A-B, B-C, C-A};
            var G2 = {C-D, D-E};
            var G_FINALE = UNIONE(G1, G2);
            PLOT G_FINALE
            """
        ),(
            "Test 7: Funzioni Custom sui Grafi",
            """
            DEF unisci_e_misura(G1, G2, start, end) = DISTANZA(UNIONE(G1, G2), start, end);
            var rete1 = {A-B, B-C};
            var rete2 = {C-D, D-E};
            var risultato = unisci_e_misura(rete1, rete2, A, E);
            IF risultato == 4 THEN
                PRINT {FUNZIONE-OK}
            ELSE
                PRINT {ERRORE}
            ENDIF
            """
        ),
        (
            "Test 8: Scoping Statico (Closure)",
            """
            var x = 10;
            DEF f(y) = x + y;
            var x = 100; 
            var risultato = f(1);
            IF risultato == 11 THEN
                PRINT {SCOPING-CORRETTO}
            ELSE
                PRINT {ERRORE-SCOPING_DINAMICO}
            ENDIF
            """
        ),
        (
            "Test 9: INCOLLA avanzato",
            """
            var ponte_sinistro = {A-B};
            var ponte_destro = {X-Y};
            var ponte_completo = INCOLLA(ponte_sinistro, ponte_destro, B, X);
            PRINT ponte_completo
            """
        )
    ]

    for name, code in test_programs:
        print(f"\n--- {name} ---")
        try:
            env, state = create_initial_env_state()
            ast = parse(code)
            execute_seq(ast, env, state)
            print("[✓] Test Superato")
        except Exception as e:
            print(f"[X] Errore nel test: {e}")

# --- MAIN ---

if __name__ == "__main__":
    import sys
    if "--repl" in sys.argv:
        REPL()
    else:
        run_tests()
