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

-- O2 (parcial na v1): interesse nas top 10 de "Para você".
-- A taxa de aceite do PRD (salvos ÷ (salvos + dispensados)) depende de R7 e R8 (P1); até lá,
-- mede-se quanto das top 10 exibidas o Leitor abriu ou marcou como "Já li".
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
