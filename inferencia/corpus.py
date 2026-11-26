"""
Base de frases em português rotuladas (positivo/negativo), construída
localmente por combinação determinística de padrões e léxico (semente fixa).

O treino roda NO BUILD da imagem (Dockerfile) e é 100% offline: o contêiner
não baixa nenhum dado ou modelo em runtime. A sofisticação do modelo NÃO
pontua no edital — ela existe apenas como carga de trabalho realista para o
sistema distribuído. Trocar este corpus pelo modelo do C1.A2 do grupo é
simples: basta substituir o que `treinar()` produz.
"""
import random

# Sujeitos (todos masculinos, para os templates com adjetivo concordarem).
SUJEITOS = [
    "o atendimento",
    "o produto",
    "o aplicativo",
    "o sistema",
    "o suporte",
    "o serviço",
    "o tutorial",
]

ADJETIVOS_POSITIVOS = [
    "excelente", "ótimo", "maravilhoso", "incrível", "perfeito",
    "fantástico", "impecável", "rápido", "confiável", "sensacional",
    "espetacular", "admirável", "brilhante", "poderoso", "intuitivo",
    "estável", "eficiente", "competente", "caprichado", "sólido",
    "vencedor", "nota dez", "impressionante", "satisfatório", "ideal",
    "correto", "cuidadoso", "rápido e confiável", "simples e eficiente",
    "melhor que o esperado",
]

ADJETIVOS_NEGATIVOS = [
    "péssimo", "horrível", "terrível", "decepcionante", "frágil",
    "lento", "bugado", "quebrado", "travando", "ruim", "insuportável",
    "inaceitável", "absurdo", "problemático", "confuso", "instável",
    "ineficiente", "incompetente", "desorganizado", "fraco",
    "cheio de defeitos", "pior que o esperado", "inacabado", "caro",
    "repetitivo", "chato", "desleixado", "lento e travando", "cheio de bugs",
]

PADRAO_POSITIVO = [
    "{sujeito} me surpreendeu positivamente",
    "{sujeito} superou as expectativas",
    "amei {sujeito}",
    "adorei {sujeito}",
    "{sujeito} funciona perfeitamente",
    "{sujeito} vale cada centavo",
    "recomendo {sujeito} de olhos fechados",
    "{sujeito} é nota dez",
    "melhor {sujeito} que já usei",
    "{sujeito} chegou rápido e impecável",
    "{sujeito} resolveu meu problema",
    "experiência incrível com {sujeito}",
    "{sujeito} nunca me decepcionou",
    "volta e meia uso {sujeito} e sempre funciona",
]

PADRAO_NEGATIVO = [
    "{sujeito} me decepcionou",
    "{sujeito} não funcionou",
    "odiei {sujeito}",
    "detestei {sujeito}",
    "{sujeito} parou de funcionar em uma semana",
    "me arrependi de {sujeito}",
    "não recomendo {sujeito}",
    "{sujeito} é um pesadelo",
    "pior {sujeito} que já usei",
    "{sujeito} chegou quebrado",
    "{sujeito} nunca resolve meu problema",
    "experiência terrível com {sujeito}",
    "{sujeito} trava toda hora",
    "todo dia algo errado com {sujeito}",
]


def base_rotulada(tamanho_maximo: int = 1500) -> list[tuple[str, str]]:
    """Gera a base (frase, rótulo) de forma determinística (semente 42)."""
    sorteio = random.Random(42)
    pares: list[tuple[str, str]] = []

    def _add(frase: str, rotulo: str, sufixo: str) -> None:
        pares.append((frase + sufixo, rotulo))

    for sujeito in SUJEITOS:
        for padrao in PADRAO_POSITIVO:
            sufixo = sorteio.choice(["!", " :)", " :D", " ⭐", ""])
            _add(padrao.format(sujeito=sujeito), "positivo", sufixo)
        for padrao in PADRAO_NEGATIVO:
            sufixo = sorteio.choice(["!", " :(", " :( ", " 👎", ""])
            _add(padrao.format(sujeito=sujeito), "negativo", sufixo)

    for sujeito in SUJEITOS:
        for adjetivo in ADJETIVOS_POSITIVOS:
            _add(f"{sujeito} foi {adjetivo}", "positivo", "")
            _add(f"achei {sujeito} {adjetivo}", "positivo", "")
            _add(f"gostei: {sujeito} está {adjetivo}", "positivo", "")
        for adjetivo in ADJETIVOS_NEGATIVOS:
            _add(f"{sujeito} ficou {adjetivo}", "negativo", "")
            _add(f"achei {sujeito} {adjetivo}", "negativo", "")
            _add(f"não gostei: {sujeito} está {adjetivo}", "negativo", "")

    # Frases únicas, embaralhadas e limitadas — treino estável e rápido.
    unicos = sorted(set(pares))
    sorteio.shuffle(unicos)
    return unicos[:tamanho_maximo]
