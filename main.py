"""
API Principal - "Busca de Livros"
Consulta a API externa Google Books e delega a persistência da estante
pessoal do usuário para a API secundária.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import requests
import os

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
API_SECUNDARIA_URL = os.getenv("API_SECUNDARIA_URL", "http://api-secundaria:8001")

app = FastAPI(
    title="API Principal - Busca de Livros",
    description=(
        "Consulta a Google Books API (externa) para buscar livros e se comunica "
        "com a API Secundária para gerenciar a estante pessoal do usuário."
    ),
    version="1.0.0",
)


class StatusLeitura(str, Enum):
    quero_ler = "quero_ler"
    lendo = "lendo"
    lido = "lido"


class LivroBusca(BaseModel):
    google_books_id: str
    titulo: str
    autores: Optional[str] = None
    capa_url: Optional[str] = None


class AdicionarEstanteRequest(BaseModel):
    google_books_id: Optional[str] = None
    titulo: str
    autores: Optional[str] = None
    capa_url: Optional[str] = None
    status: StatusLeitura = StatusLeitura.quero_ler
    nota: Optional[int] = Field(default=None, ge=0, le=5)


class AtualizarEstanteRequest(BaseModel):
    status: Optional[StatusLeitura] = None
    nota: Optional[int] = Field(default=None, ge=0, le=5)


@app.get("/", tags=["Status"])
def raiz():
    return {"servico": "API Principal - Busca de Livros", "status": "online"}


@app.get("/livros/buscar", response_model=List[LivroBusca], tags=["Busca (API externa)"])
def buscar_livros(q: str, limite: int = 10):
    """
    Busca livros na Google Books API (serviço externo) por título, autor ou assunto.
    Os dados retornados já são tratados/normalizados por esta API.
    """
    if not q:
        raise HTTPException(status_code=400, detail="Informe um termo de busca em 'q'")

    params = {"q": q, "maxResults": min(limite, 40)}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    try:
        resposta = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível conectar à Google Books API: {erro}",
        )

    if resposta.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Google Books respondeu {resposta.status_code}: "
                f"{resposta.text[:300]}"
            ),
        )

    itens = resposta.json().get("items", [])
    resultado = []
    for item in itens:
        info = item.get("volumeInfo", {})
        resultado.append(
            LivroBusca(
                google_books_id=item.get("id", ""),
                titulo=info.get("title", "Título desconhecido"),
                autores=", ".join(info.get("authors", [])) or None,
                capa_url=info.get("imageLinks", {}).get("thumbnail"),
            )
        )
    return resultado


@app.get("/livros/estante", tags=["Estante (via API secundária)"])
def listar_estante(status: Optional[StatusLeitura] = None):
    """Lista os livros da estante pessoal (delegado à API secundária)."""
    params = {"status": status.value} if status else {}
    resp = requests.get(f"{API_SECUNDARIA_URL}/estante", params=params, timeout=10)
    _validar_resposta(resp)
    return resp.json()


@app.post("/livros/estante", status_code=201, tags=["Estante (via API secundária)"])
def adicionar_a_estante(livro: AdicionarEstanteRequest):
    """Adiciona um livro encontrado na busca à estante pessoal do usuário."""
    resp = requests.post(f"{API_SECUNDARIA_URL}/estante", json=livro.model_dump(), timeout=10)
    _validar_resposta(resp)
    return resp.json()


@app.put("/livros/estante/{livro_id}", tags=["Estante (via API secundária)"])
def atualizar_na_estante(livro_id: int, dados: AtualizarEstanteRequest):
    """Atualiza status de leitura e/ou nota de um livro da estante."""
    resp = requests.put(
        f"{API_SECUNDARIA_URL}/estante/{livro_id}",
        json=dados.model_dump(exclude_none=True),
        timeout=10,
    )
    _validar_resposta(resp)
    return resp.json()


@app.delete("/livros/estante/{livro_id}", status_code=204, tags=["Estante (via API secundária)"])
def remover_da_estante(livro_id: int):
    """Remove um livro da estante pessoal."""
    resp = requests.delete(f"{API_SECUNDARIA_URL}/estante/{livro_id}", timeout=10)
    _validar_resposta(resp)
    return None


def _validar_resposta(resp: requests.Response):
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Livro não encontrado na estante")
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502, detail="Falha na comunicação com a API secundária"
        )
