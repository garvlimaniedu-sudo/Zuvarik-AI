"""
Minimal logistic regression — pure Python, stdlib only (no numpy/sklearn),
matching this project's zero-install philosophy (see db.py's docstring).
Gradient descent with L2 regularization. Small enough to train in seconds
on the feature/example counts this project produces per fold.
"""

import math


def sigmoid(z):
    z = max(min(z, 35), -35)  # avoid overflow
    return 1 / (1 + math.exp(-z))


def standardize(X):
    """Z-score each feature column. Returns (X_scaled, means, stds)."""
    n = len(X)
    d = len(X[0])
    means = [sum(row[j] for row in X) / n for j in range(d)]
    stds = []
    for j in range(d):
        variance = sum((row[j] - means[j]) ** 2 for row in X) / n
        stds.append(variance ** 0.5 or 1.0)
    X_scaled = [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in X]
    return X_scaled, means, stds


def apply_standardize(X, means, stds):
    return [[(row[j] - means[j]) / stds[j] for j in range(len(row))] for row in X]


def train(X, y, lr=0.1, epochs=300, l2=0.001):
    n = len(X)
    d = len(X[0])
    w = [0.0] * d
    b = 0.0

    for _ in range(epochs):
        grad_w = [0.0] * d
        grad_b = 0.0
        for xi, yi in zip(X, y):
            z = sum(wj * xj for wj, xj in zip(w, xi)) + b
            p = sigmoid(z)
            err = p - yi
            for j in range(d):
                grad_w[j] += err * xi[j]
            grad_b += err
        for j in range(d):
            w[j] -= lr * (grad_w[j] / n + l2 * w[j])
        b -= lr * (grad_b / n)

    return w, b


def predict_proba(x, w, b):
    z = sum(wj * xj for wj, xj in zip(w, x)) + b
    return sigmoid(z)
