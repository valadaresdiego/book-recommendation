# A v1 roda local, em Streamlit, sem login

O PRD previa um web app hospedado com login (R6). A v1 roda **só no computador do Leitor**: interface em Streamlit, PostgreSQL local (Docker, com pgvector), cálculos na GPU local (RTX 3060) e atualização a cada vez que o PC liga. Sem login. Python foi escolhido de ponta a ponta porque o núcleo do produto são os modelos de recomendação, e manter um segundo runtime (TypeScript) não se paga para um usuário só. A hospedagem fica para uma segunda onda.

## Opções consideradas

- **Cloudflare Pages + Supabase (gratuitos):** rejeitado na v1. O limite de CPU por requisição impede Python no servidor web, o banco gratuito tem 500 MB e o projeto pausa após 7 dias sem uso.

## Consequências

- Não há acesso pelo celular fora da rede local. A meta O3 (< 30 s para registrar uma Leitura) passa a ser medida no desktop.
- `usuario_id` continua em tudo que é pessoal, com um Leitor fixo, para não fechar a porta ao multiusuário e à hospedagem.
- Streamlit amarra a interface: hospedar com vários usuários provavelmente vai exigir reescrever a UI, mas não o pipeline nem o banco.
