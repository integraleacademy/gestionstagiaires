"""Aggregate the submitted copies of one formative unit, across questionnaire editions."""
from dataclasses import dataclass, field

import uv_questionnaires as uv


class ReportUnavailable(ValueError):
    pass


@dataclass
class Participant:
    name: str
    initials: str
    photo_token: str
    score: int | None
    status: str


@dataclass
class QuestionResult:
    number: int
    prompt: str
    answer: str
    versions: set[str] = field(default_factory=set)
    correct: int = 0
    wrong: int = 0
    blank: int = 0

    @property
    def total(self):
        return self.correct + self.wrong + self.blank


@dataclass
class UnitReport:
    participants: list[Participant]
    questions: list[QuestionResult]
    scores: list[int]
    versions: set[str]


def summarize(people, course, number):
    participants, scores = [], []
    questions, editions = {}, {}
    for person in people:
        first = str(person.get('first_name') or '').strip()
        last = str(person.get('last_name') or '').strip()
        name = ' '.join(part for part in (first, last) if part) or str(person['id'])
        result = uv._result(person, course, number)
        score = None
        status = 'En cours' if uv._entry(person, 'uv_questionnaire_attempts', course, number) else 'Non commencé'
        if result:
            version = result.get('version')
            if not isinstance(version, str):
                raise ReportUnavailable('La version utilisée par un stagiaire est indisponible.')
            if version not in editions:
                try:
                    edition = uv.unit(course, number, version)
                except (ValueError, OSError):
                    edition = None
                if not edition:
                    raise ReportUnavailable('La version utilisée par un stagiaire est indisponible.')
                editions[version] = edition['questions']
            presented = editions[version]
            answers = result.get('answers')
            if not isinstance(answers, dict):
                raise ReportUnavailable('Le détail des réponses d’une copie est indisponible.')
            try:
                calculated = uv.grade(presented, answers)
            except (ValueError, TypeError):
                raise ReportUnavailable('Les réponses archivées d’une copie sont incomplètes ou illisibles.') from None
            score = result.get('score', calculated)
            if type(score) is not int or not 0 <= score <= len(presented):
                raise ReportUnavailable('La note archivée d’une copie est illisible.')
            scores.append(score)
            status = 'Terminé'
            for position, question in enumerate(presented, 1):
                options = {option['id']: option['text'] for option in question['options']}
                answer = options[question['answer']]
                # A reused question ID can refer to a different prompt, key or set of choices.
                key = (position, question['prompt'], tuple(options.values()), answer)
                if key not in questions:
                    questions[key] = QuestionResult(position, question['prompt'], answer)
                tally = questions[key]
                tally.versions.add(version)
                selected = answers[question['id']]
                if selected == question['answer']:
                    tally.correct += 1
                elif selected:
                    tally.wrong += 1
                else:
                    tally.blank += 1
        participants.append(Participant(name, (first[:1] + last[:1]).upper() or '–',
                                        person.get('identity_photo') or '', score, status))
    if not scores:
        raise ReportUnavailable('Le rapport sera disponible dès la première copie remise pour cette UV.')
    ordered = sorted(questions.values(), key=lambda q: (q.number, min(q.versions)))
    return UnitReport(participants, ordered, scores, set(editions))
