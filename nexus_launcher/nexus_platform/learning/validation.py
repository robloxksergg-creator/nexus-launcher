"""Pluggable validators observing semantic editor events and snapshots."""
from dataclasses import dataclass
from typing import Any, Protocol


class EditorAdapter(Protocol):
    def snapshot(self) -> dict[str, Any]: ...
    def resolve_target(self, target) -> Any: ...


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    progress: float = 0
    message: str = ''
    hint: str = ''


class ValidationEngine:
    def __init__(self):
        self.validators = {'action': self.action, 'property': self.property,
                           'component': self.component, 'layout': self.layout,
                           'state': self.state}

    def register(self, name, validator):
        if name in self.validators:
            raise ValueError('Validator already registered')
        self.validators[name] = validator

    def validate(self, rule, event, snapshot, baseline):
        name = rule.get('kind', 'action')
        if name not in self.validators:
            return ValidationResult(False, message='feedback.unsupported')
        return self.validators[name](rule, event, snapshot, baseline)

    @staticmethod
    def action(rule, event, _snapshot, _baseline):
        ok = event.get('type') == rule.get('event') and all(event.get(k) == v for k, v in rule.get('matches', {}).items())
        return ValidationResult(ok)

    @staticmethod
    def component(rule, event, snapshot, _baseline):
        items = snapshot.get('components', [])
        matches = [item for item in items if all(item.get(k) == v for k, v in rule.get('matches', {}).items())]
        return ValidationResult(len(matches) >= rule.get('count', 1) and
                                (not rule.get('event') or event.get('type') == rule['event']))

    @staticmethod
    def property(rule, event, snapshot, baseline):
        key = rule['property']
        item = next((x for x in snapshot.get('components', []) if x['id'] == event.get('componentId')), None)
        if not item or event.get('type') != rule.get('event'):
            return ValidationResult(False)
        value = item.get(key)
        if 'min_length' in rule:
            ok = isinstance(value, str) and len(value.strip()) >= rule['min_length']
        elif 'value' in rule:
            ok = abs(value - rule['value']) <= rule.get('tolerance', 0) if isinstance(value, (int, float)) else value == rule['value']
        else:
            old = next((x for x in baseline.get('components', []) if x['id'] == item['id']), {})
            ok = isinstance(value, (int, float)) and isinstance(old.get(key), (int, float)) and (value - old[key] if rule.get('direction') == 'increase' else abs(value - old[key])) >= rule.get('delta', 2)
        return ValidationResult(ok, message='' if ok else 'feedback.almost')

    @staticmethod
    def layout(rule, event, snapshot, baseline):
        return ValidationEngine.property(rule, event, snapshot, baseline)

    @staticmethod
    def state(rule, _event, snapshot, _baseline):
        return ValidationResult(all(snapshot.get(k) == v for k, v in rule.get('matches', {}).items()))
