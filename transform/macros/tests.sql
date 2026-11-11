{# Fails on any repeated combination of the given columns. #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as copies
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{# Fails on any row where the expression is false. #}
{% test expression_true(model, column_name, expression) %}
select * from {{ model }} where not ({{ expression }})
{% endtest %}
