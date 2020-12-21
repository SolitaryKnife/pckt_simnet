import torch
import torch.nn as nn

import typing as _T


def fully_connected(channels, activation=None, bias=True):

    in_channels = channels[:-1]  # Except Last
    out_channels = channels[1:]  # Except First

    if not isinstance(activation, (list, tuple)):
        activation = [activation] * len(in_channels)
    assert len(activation) == len(in_channels)
    assert all([a is None or callable(a) for a in activation])

    if not isinstance(bias, (list, tuple)):
        bias = [bias] * len(in_channels)
    assert len(bias) == len(in_channels)
    bias = [bool(b) for b in bias]

    layers = []
    for i, o, b, a in zip(in_channels, out_channels, bias, activation):
        layers.append(nn.Linear(in_features=i, out_features=o, bias=b))
        if a is not None:
            layers.append(a())

    return layers


class Simnet(nn.Sequential):
    def __init__(self, in_channels, channels=[256, 128, 64, 10]):
        layers = fully_connected([in_channels * 2] + channels, activation=nn.ReLU, bias=True)[:-1]
        super().__init__(
            *layers,
            nn.Tanh()
        )

    def forward(self, a, b):
        x = torch.cat([a, b], dim=1)
        return super().forward(x).mean(dim=1)


class SimnetClassifier(nn.Module):

    def __init__(self, *args, **kwds):
        super().__init__()
        self.simnet = Simnet(*args, **kwds)

    def forward(self, queries: torch.Tensor, *supports: _T.List[torch.Tensor]):
        assert queries.dim() == 2

        num_query, num_dim = queries.size()
        num_classes = len(supports)

        assert all([class_supports.dim() == 2 for class_supports in supports])
        assert all([class_supports.size(1) == num_dim for class_supports in supports])

        scores = []
        for class_supports in supports:
            class_score = 0
            num_support = class_supports.size(0)
            for i in range(num_support):
                item = class_supports[i]
                item = item.unsqueeze(0).repeat(num_query, 1)
                item_score = self.simnet(queries, item)
                if item_score.dim() == 1:
                    item_score.unsqueeze_(1)
                assert item_score.dim() == 2
                class_score += item_score
            scores.append(class_score)
            assert class_score.dim() == 2

        scores = torch.cat(scores, dim=1)
        assert scores.size() == (num_query, num_classes)
        return scores


class Protonet(nn.Sequential):

    def __init__(self, in_channels, out_channels, mid_channels=[256, 128, 64]):
        layers = fully_connected([in_channels, *mid_channels, out_channels], activation=nn.ReLU, bias=True)[:-1]
        super().__init__(*layers)


class ProtonetClassifier(nn.Module):

    def __init__(self, *args, **kwds):
        self.protonet = Protonet(*args, **kwds)

    def compute_prototype(self, features: torch.Tensor):
        return features.mean(dim=1, keepdim=True)

    def pairwise_distance(x, y):
        assert x.dim() == 2
        assert y.dim() == 2
        x = x.unsqueeze(0)
        y = y.unsqueeze(0)
        return torch.cdist(x, y, p=2).squeeze(0)

    def forward(self, queries, *supports):
        assert queries.dim() == 2

        num_query, num_dim = queries.size()
        num_classes = len(supports)

        assert all([class_supports.dim() == 2 for class_supports in supports])
        assert all([class_supports.size(1) == num_dim for class_supports in supports])

        queries = self.protonet(queries)
        num_query, num_feat = queries.size()

        prototypes = []
        for class_support in supports:
            prototype = self.protonet(class_support)
            assert prototype.size(1) == num_feat
            prototype = self.compute_prototype(prototype)
            prototypes.append(prototype)

        prototypes = torch.cat(prototypes, dim=0)
        assert prototypes.size() == (num_classes, num_feat)

        scores = -self.pairwise_distance(queries, prototypes)
        assert scores.size() == (num_query, num_classes)
        return scores
