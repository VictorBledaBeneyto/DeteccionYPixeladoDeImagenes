"""
Entrena un ResNet-50 para regresión de edad sobre el dataset facial-age.

Uso:
    python train.py --dataset /ruta/al/dataset --epochs 20 --output age_model.pth
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
from torchvision import transforms, models
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ── Dataset ────────────────────────────────────────────────────────────────────

class FaceAgeDataset(Dataset):
    """
    Espera la estructura: dataset_root/{1,2,...,100}/*.jpg|*.png
    El nombre de la carpeta es la edad (int).
    """
    def __init__(self, root: str, transform=None):
        self.samples = []
        self.transform = transform

        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir():
                continue
            try:
                age = int(folder.name)
            except ValueError:
                continue
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                for img_path in folder.glob(ext):
                    self.samples.append((str(img_path), float(age)))

        ages = [s[1] for s in self.samples]
        print(f"Dataset cargado: {len(self.samples)} imágenes, edades {int(min(ages))}-{int(max(ages))}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, age = self.samples[idx]
        img = np.array(Image.open(path).convert("RGB"))
        if self.transform:
            img = self.transform(image=img)["image"]
        return img, torch.tensor(age, dtype=torch.float32)


# ── Augmentación (misma pipeline que la práctica de radiología) ────────────────

def get_transforms(augment: bool):
    """
    Augmentación con Albumentations:
      - RandomBrightnessContrast  p=0.5
      - CLAHE                     p=0.2
      - Rotate (max 10°)          p=0.3
      - HorizontalFlip            p=0.1
    """
    aug_steps = []
    if augment:
        aug_steps = [
            A.RandomBrightnessContrast(p=0.5),
            A.CLAHE(p=0.2),
            A.Rotate(limit=10, p=0.3),
            A.HorizontalFlip(p=0.1),
        ]

    return A.Compose(aug_steps + [
        A.Resize(224, 224),
        A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ToTensorV2(),
    ])


# ── Modelo ─────────────────────────────────────────────────────────────────────

def build_model():
    """ResNet-50 preentrenado en ImageNet, base congelada, cabeza de regresión."""
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    for param in model.parameters():
        param.requires_grad = False
    for param in model.layer4.parameters():
        param.requires_grad = True
    model.fc = nn.Sequential(
        nn.Linear(model.fc.in_features, 256),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(256, 1),
    )
    return model


# ── Métricas ───────────────────────────────────────────────────────────────────

def binary_accuracy(preds: torch.Tensor, ages: torch.Tensor) -> float:
    """Accuracy binaria <18 / ≥18 — la decisión que usa el pipeline."""
    pred_menor = preds < 18
    true_menor = ages < 18
    return (pred_menor == true_menor).float().mean().item()


# ── Curvas de entrenamiento ────────────────────────────────────────────────────

def save_plots(history: dict, output_dir: str):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    epochs = range(1, len(history["train_mae"]) + 1)

    # Gráfica 1: MAE entrenamiento y validación
    ax1.plot(epochs, history["train_mae"], label="Train MAE")
    ax1.plot(epochs, history["val_mae"],   label="Val MAE")
    ax1.set_title("Pérdida (MAE) por época")
    ax1.set_xlabel("Época")
    ax1.set_ylabel("MAE (años)")
    ax1.legend()
    ax1.grid(True)

    # Gráfica 2: Accuracy binaria <18/≥18 entrenamiento y validación
    ax2.plot(epochs, history["train_acc"], label="Train Acc <18/≥18")
    ax2.plot(epochs, history["val_acc"],   label="Val Acc <18/≥18")
    ax2.set_title("Accuracy binaria <18 / ≥18 por época")
    ax2.set_xlabel("Época")
    ax2.set_ylabel("Accuracy")
    ax2.set_ylim(0, 1)
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()
    out_path = os.path.join(output_dir, "training_curves.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Curvas guardadas en {out_path}")


# ── Entrenamiento ──────────────────────────────────────────────────────────────

def train(dataset_root: str, epochs: int, output: str, batch_size: int, patience: int):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Usando dispositivo: {device}")

    train_tf = get_transforms(augment=True)
    val_tf   = get_transforms(augment=False)

    full_dataset = FaceAgeDataset(dataset_root, transform=train_tf)
    val_size     = int(len(full_dataset) * 0.2)
    train_size   = len(full_dataset) - val_size
    train_ds, val_ds = random_split(full_dataset, [train_size, val_size])

    # El subset de validación usa transforms sin augmentación
    val_ds.dataset.transform = val_tf

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,  num_workers=4)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False, num_workers=4)

    model     = build_model().to(device)
    criterion = nn.L1Loss()
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4
    )
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=3, gamma=0.5)

    output_dir = os.path.dirname(output) or "."
    os.makedirs(output_dir, exist_ok=True)

    history = {"train_mae": [], "val_mae": [], "train_acc": [], "val_acc": []}

    best_val_mae   = float("inf")
    epochs_no_improve = 0

    for epoch in range(1, epochs + 1):

        # ── Train ──────────────────────────────────────────────────────────────
        model.train()
        train_loss, train_acc_sum = 0.0, 0.0
        for imgs, ages in train_loader:
            imgs, ages = imgs.to(device), ages.to(device)
            optimizer.zero_grad()
            preds = model(imgs).squeeze(1)
            loss  = criterion(preds, ages)
            loss.backward()
            optimizer.step()
            train_loss    += loss.item() * len(imgs)
            train_acc_sum += binary_accuracy(preds.detach(), ages) * len(imgs)

        train_mae = train_loss    / train_size
        train_acc = train_acc_sum / train_size

        # ── Validación ─────────────────────────────────────────────────────────
        model.eval()
        val_loss, val_acc_sum = 0.0, 0.0
        with torch.no_grad():
            for imgs, ages in val_loader:
                imgs, ages = imgs.to(device), ages.to(device)
                preds = model(imgs).squeeze(1)
                val_loss    += criterion(preds, ages).item() * len(imgs)
                val_acc_sum += binary_accuracy(preds, ages) * len(imgs)

        val_mae = val_loss    / val_size
        val_acc = val_acc_sum / val_size

        scheduler.step()

        history["train_mae"].append(train_mae)
        history["val_mae"].append(val_mae)
        history["train_acc"].append(train_acc)
        history["val_acc"].append(val_acc)

        print(
            f"Época {epoch:2d}/{epochs} — "
            f"train MAE: {train_mae:.2f} años  acc: {train_acc:.3f} | "
            f"val MAE: {val_mae:.2f} años  acc: {val_acc:.3f}"
        )

        # ── ModelCheckpoint: guarda si mejora ──────────────────────────────────
        if val_mae < best_val_mae:
            best_val_mae = val_mae
            torch.save(model.state_dict(), output)
            print(f"  → Mejor modelo guardado (val MAE={val_mae:.2f}, acc={val_acc:.3f})")
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1

        # ── Early stopping ─────────────────────────────────────────────────────
        if epochs_no_improve >= patience:
            print(f"\nEarly stopping en época {epoch} (sin mejora en {patience} épocas).")
            break

    print(f"\nEntrenamiento completado. Mejor val MAE: {best_val_mae:.2f} años")
    print(f"Modelo guardado en: {output}")

    save_plots(history, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="/home/dorfin/dataset/face_age")
    parser.add_argument("--epochs",  type=int, default=20)
    parser.add_argument("--output",  default="age_model.pth")
    parser.add_argument("--batch",   type=int, default=32)
    parser.add_argument("--patience",type=int, default=5)
    args = parser.parse_args()

    train(args.dataset, args.epochs, args.output, args.batch, args.patience)
