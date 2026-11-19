-- Consultas das metas do PRD §7 sobre a tabela `evento` (SPEC §7.6).
-- Rodar no banco do app, por exemplo:
--   docker compose exec -T db psql -U recomendador -d recomendador -f - < reports/consultas-metricas.sql
-- Todas filtram pelo Leitor único da v1 (config.LEITOR_ID).

\set leitor '''00000000-0000-0000-0000-000000000001'''

-- Indicador rápido: Leituras com Nota na Estante, total e na 1ª semana de uso (meta ≥ 20).
SELECT count(*) FILTER (WHERE nota IS NOT NULL) AS leituras_com_nota,
       count(*) FILTER (
           WHERE nota IS NOT NULL
             AND criado_em < (SELECT min(criado_em) FROM leitura WHERE leitor_id = :leitor)
                             + interval '7 days'
       ) AS com_nota_na_1a_semana
FROM leitura
WHERE leitor_id = :leitor;

-- O3: tempo para adicionar + dar Nota (meta: média < 30 s), por semana.
-- `duracao_s` é o tempo desde o último `busca_iniciada` da sessão; só existe nas Leituras
-- que vieram de uma busca (origem 'busca' ou 'manual').
SELECT date_trunc('week', criado_em)::date AS semana,
       count(*) AS leituras,
       round(avg((dados ->> 'duracao_s')::numeric), 1) AS media_s,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY (dados ->> 'duracao_s')::numeric)::numeric, 1)
           AS mediana_s,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY (dados ->> 'duracao_s')::numeric)::numeric, 1)
           AS p90_s,
       count(*) FILTER (WHERE (dados ->> 'duracao_s')::numeric < 30) AS abaixo_de_30_s
FROM evento
WHERE leitor_id = :leitor
  AND tipo = 'leitura_salva'
  AND (dados ->> 'com_nota')::boolean
  AND dados ->> 'duracao_s' IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- O2: taxa de aceite das top 10 de "Para você" (PRD §7: meta ≥ 50 %, ambicioso ≥ 70 %).
-- Salvas em Quero ler ÷ (salvas + dispensadas), contando cada Obra uma vez, pela última
-- reação dela enquanto estava nas top 10 (SPEC §8.6). Vale também quando a reação veio da
-- página da Obra aberta a partir de "Para você", que guarda a posição.
-- Uma linha por lista (SPEC §8.8): `geral` e `tecnologia`. Os eventos de antes da fase 6
-- não têm o campo e contam como `geral`.
WITH reacoes AS (
    SELECT DISTINCT ON (obra_id) obra_id, tipo, coalesce(dados ->> 'lista', 'geral') AS lista
    FROM evento
    WHERE leitor_id = :leitor
      AND tipo IN ('quero_ler_salvo', 'sugestao_dispensada')
      AND (dados ->> 'posicao')::int <= 10
    ORDER BY obra_id, criado_em DESC, id DESC
)
SELECT lista,
       count(*) FILTER (WHERE tipo = 'quero_ler_salvo') AS salvas,
       count(*) FILTER (WHERE tipo = 'sugestao_dispensada') AS dispensadas,
       round(100.0 * count(*) FILTER (WHERE tipo = 'quero_ler_salvo') / nullif(count(*), 0), 1)
           AS pct_aceite
FROM reacoes
GROUP BY lista
ORDER BY lista;

-- O2, complemento: interesse nas top 10 exibidas, medido por quanto o Leitor abriu ou
-- marcou como "Já li".
WITH exibidas AS (
    SELECT obra_id, criado_em
    FROM evento
    WHERE leitor_id = :leitor AND tipo = 'sugestao_exibida' AND (dados ->> 'posicao')::int <= 10
),
reacoes AS (
    SELECT tipo, obra_id
    FROM evento
    WHERE leitor_id = :leitor
      AND tipo IN ('sugestao_aberta', 'ja_li_de_sugestao')
      AND (dados ->> 'posicao')::int <= 10
)
SELECT (SELECT count(*) FROM exibidas) AS exibicoes_top10,
       (SELECT count(DISTINCT obra_id) FROM exibidas) AS obras_exibidas_top10,
       (SELECT count(DISTINCT obra_id) FROM reacoes WHERE tipo = 'sugestao_aberta') AS abertas,
       (SELECT count(DISTINCT obra_id) FROM reacoes WHERE tipo = 'ja_li_de_sugestao') AS ja_li,
       round(
           100.0 * (SELECT count(DISTINCT obra_id) FROM reacoes)
           / nullif((SELECT count(DISTINCT obra_id) FROM exibidas), 0),
           1
       ) AS pct_obras_com_reacao;

-- O5: Nota média das Obras lidas a partir de uma Sugestão (meta ≥ 4, e ≥ 3 Obras em 3 meses),
-- comparada com a Nota média da Estante.
SELECT (SELECT count(*) FROM leitura WHERE leitor_id = :leitor AND origem = 'sugestao')
           AS lidas_de_sugestao,
       (SELECT round(avg(nota), 2) FROM leitura
         WHERE leitor_id = :leitor AND origem = 'sugestao' AND nota IS NOT NULL)
           AS nota_media_de_sugestao,
       (SELECT round(avg((dados ->> 'nota')::numeric), 2) FROM evento
         WHERE leitor_id = :leitor AND tipo = 'ja_li_de_sugestao' AND dados ->> 'nota' IS NOT NULL)
           AS nota_media_no_evento,
       (SELECT round(avg(nota), 2) FROM leitura WHERE leitor_id = :leitor AND nota IS NOT NULL)
           AS nota_media_da_estante;

-- SPEC §14, fase 3: taxa de correspondência das Leituras com Obras da Base de coleitura
-- (meta ≥ 40 %; abaixo disso, reabrir a escolha da Base, PRD §9).
SELECT count(*) AS leituras,
       count(*) FILTER (WHERE o.origem = 'base') AS ligadas_a_base,
       round(100.0 * count(*) FILTER (WHERE o.origem = 'base') / nullif(count(*), 0), 1)
           AS pct_base
FROM leitura l JOIN obra o ON o.id = l.obra_id
WHERE l.leitor_id = :leitor;

-- O4: Leituras com R5a ("Parecidos com este", meta ≥ 80 %) e R5b ("Quem leu este também
-- gostou", meta ≥ 40 %) preenchidos, pelas execuções ativas de cada tipo.
SELECT count(*) AS leituras,
       round(100.0 * count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM vizinho v JOIN execucao_modelo e ON e.id = v.execucao_id
           WHERE v.obra_id = l.obra_id AND e.ativa AND e.tipo = 'conteudo'
       )) / nullif(count(*), 0), 1) AS pct_r5a,
       round(100.0 * count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM vizinho v JOIN execucao_modelo e ON e.id = v.execucao_id
           WHERE v.obra_id = l.obra_id AND e.ativa AND e.tipo = 'coleitura'
       )) / nullif(count(*), 0), 1) AS pct_r5b
FROM leitura l
WHERE l.leitor_id = :leitor;
