"""Select one AFC exam without copying or persisting a second training session."""
from collections.abc import MutableMapping

import afc_schedule


class ExamContext(MutableMapping):
    def __init__(self, training, family):
        self.training = training
        self.family = family

    def __getitem__(self, key):
        if key == "_exam_family":
            return self.family
        return self.training[key]

    def __setitem__(self, key, value):
        self.training[key] = value

    def __delitem__(self, key):
        del self.training[key]

    def __iter__(self):
        return iter(self.training)

    def __len__(self):
        return len(self.training)


def for_family(training, family):
    if isinstance(training, ExamContext):
        training = training.training
    if training and afc_schedule.enabled(training):
        return ExamContext(training, family)
    return training


def all_exams(trainings):
    for training in trainings:
        if afc_schedule.enabled(training):
            yield for_family(training, "security")
        yield training
