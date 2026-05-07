"""
Entrena ResNet-50 como clasificador binario <18 / >=18 sobre el dataset facial-age.

Enfoque identico a la practica de radiologia:
  - Transferencia de conocimiento: ResNet-50 ImageNet, base congelada, solo layer4 + cabeza entrenable
  - Augmentacion con Albumentations: RandomBrightnessContrast / CLAHE / Rotate / HorizontalFlip
  - BCEWithLogitsLoss (equivalente a binary_crossentropy con sigmoid estable)
  - Adam optimizer
  - ModelCheckpoint (guarda mejor val_accuracy, igual que la practica)
  - EarlyStopping (paciencia configurable)
  - Curvas de perdida y accuracy (identicas a la practica de radiologia)

Etiqueta: 1.0 = menor (<18)  /  0.0 = adulto (>=18)
Score almacenado en BD: sigmoid(logit) in [0, 1] = probabilidad de ser menor

Uso:
    python train_classifier.py --dataset /ruta/dataset --epochs 20 --output age_model.pth
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler, random_split
from torchvision import models
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ── Dataset ────────────────────────────────────────────────────────────────────

class FaceAgeDataset(Dataset):
    """
    Espera: dataset_root/{1,2,...,116}/*.jpg|*.png
    Etiqueta binaria: 1.0 = menor (<18), 0.0 = adulto (>=18)
    """
    def __init__(self, root: str, transform=None):
        self.samples  = []
        self.transform = transform

        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir():
                continue
            try:
                age = int(folder.name)
            except ValueError:
                continue
            label = 1.0 if age < 18 else 0.0
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                for img_path in folder.glob(ext):
                    self.samples.append((str(img_path), label))

        labels   = [s[1] for s in self.samples]
        n_minor  = int(sum(labels))
        n_adult  = len(labels) - n_minor
        print(f"Dataset: {len(self.samples):,} imagenes  |  "
              f"menores (<18): {n_minor:,}  adultos (>=18): {n_adult:,}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img = np.array(Image.open(path).convert("RGB"))
        if self.transform:
            img = self.transform(image=img)["image"]
        return img, torch.tensor(label, dtype=torch.float32)


# ── Augmentacion (misma pipeline que la practica de radiologia) ───────────────

def get_transforms(augment: bool):
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
    """ResNet-50 ImageNet, base congelada, cabeza de clasificacion binaria."""
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    for param in model.parameters():
        param.requires_grad = False
    for param in model.layer4.parameters():
        param.requires_grad = True
    # Cabeza identica a la practica de radiologia (Dense -> sigmoid)
    # Sin sigmoid aqui: BCEWithLogitsLoss lo aplica internamente (mas estable)
    model.fc = nn.Sequential(
        nn.Linear(model.fc.in_features, 256),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(256, 1),
    )
    total     = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Parametros totales: {total:,}  |  entrenables: {trainable:,} ({100*trainable/total:.1f}%)")
    return model


# ── Metrica ────────────────────────────────────────────────────────────────────

def binary_accuracy(logits: torch.Tensor, labels: torch.Tensor) -> float:
    preds = (torch.sigmoid(logits) > 0.5).float()
    return (preds == labels).float().mean().item()


# ── Curvas de entrenamiento (estilo practica de radiologia) ───────────────────

def save_plots(history: dict, output_dir: str):
    epochs = range(1, len(history["train_loss"]) + 1)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(epochs, history["train_loss"], label="Entrenamiento", marker="o")
    ax1.plot(epochs, history["val_loss"],   label="Validacion",    marker="s")
    ax1.set_title("Perdida (BCE) por epoca")
    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("BCE Loss")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(epochs, history["train_acc"], label="Entrenamiento", marker="o")
    ax2.plot(epochs, history["val_acc"],   label="Validacion",    marker="s")
    ax2.set_title("Accuracy binaria <18 / >=18 por epoca")
    ax2.set_xlabel("Epoca")
    ax2.set_ylabel("Accuracy")
    ax2.set_ylim(0, 1)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(output_dir, "training_curves.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Curvas guardadas en {out_path}")


# ── Entrenamiento ──────────────────────────────────────────────────────────────

def train(dataset_root: str, epochs: int, output: str, batch_size: int, patience: int):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Dispositivo: {device}")

    train_tf = get_transforms(augment=True)
    val_tf   = get_transforms(augment=False)

    full_dataset = FaceAgeDataset(dataset_root, transform=train_tf)
    val_size     = int(len(full_dataset) * 0.2)
    train_size   = len(full_dataset) - val_size
    train_ds, val_ds = random_split(
        full_dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42)
    )
    val_ds.dataset.transform = val_tf

    # WeightedRandomSampler para compensar el desbalance menores/adultos
    train_labels  = [full_dataset.samples[i][1] for i in train_ds.indices]
    n_minor       = int(sum(train_labels))
    n_adult       = len(train_labels) - n_minor
    w_minor       = (n_minor + n_adult) / (2 * n_minor) if n_minor > 0 else 1.0
    w_adult       = (n_minor + n_adult) / (2 * n_adult) if n_adult > 0 else 1.0
    sample_w      = [w_minor if lbl == 1.0 else w_adult for lbl in train_labels]
    sampler       = WeightedRandomSampler(sample_w, num_samples=len(sample_w), replacement=True)

    # pos_weight para BCEWithLogitsLoss (compensa desbalance en la funcion de perdida)
    pos_weight = torch.tensor([n_adult / n_minor], dtype=torch.float32).to(device) if n_minor > 0 else None
    print(f"Train: {train_size:,}  Val: {val_size:,}  |  "
          f"menores train: {n_minor:,}  adultos: {n_adult:,}  pos_weight: {pos_weight.item():.2f}")

    train_loader = DataLoader(train_ds, batch_size=batch_size, sampler=sampler, num_workers=4)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False,   num_workers=4)

    model     = build_model().to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4
    )
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=3, gamma=0.5)

    output_dir = os.path.dirname(os.path.abspath(output))
    os.makedirs(output_dir, exist_ok=True)

    history           = {"train_loss": [], "val_loss": [], "train_acc": [], "val_acc": []}
    best_val_acc      = 0.0
    best_val_loss     = float("inf")
    epochs_no_improve = 0

    for epoch in range(1, epochs + 1):

        # ── Train ──────────────────────────────────────────────────────────────
        model.train()
        train_loss_sum, train_acc_sum = 0.0, 0.0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(imgs).squeeze(1)
            loss   = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            train_loss_sum += loss.item() * len(imgs)
            train_acc_sum  += binary_accuracy(logits.detach(), labels) * len(imgs)

        train_loss = train_loss_sum / train_size
        train_acc  = train_acc_sum  / train_size

        # ── Validacion ─────────────────────────────────────────────────────────
        model.eval()
        val_loss_sum, val_acc_sum = 0.0, 0.0
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                logits = model(imgs).squeeze(1)
                val_loss_sum += criterion(logits, labels).item() * len(imgs)
                val_acc_sum  += binary_accuracy(logits, labels)  * len(imgs)

        val_loss = val_loss_sum / val_size
        val_acc  = val_acc_sum  / val_size

        scheduler.step()
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["train_acc"].append(train_acc)
        history["val_acc"].append(val_acc)

        print(
            f"Epoca {epoch:2d}/{epochs}  "
            f"train loss: {train_loss:.4f}  acc: {train_acc:.3f}  |  "
            f"val loss: {val_loss:.4f}  acc: {val_acc:.3f}"
        )

        # ── ModelCheckpoint: guarda si mejora val_accuracy (igual que radiologia) ─
        if val_acc > best_val_acc or (val_acc == best_val_acc and val_loss < best_val_loss):
            best_val_acc  = val_acc
            best_val_loss = val_loss
            torch.save(model.state_dict(), output)
            print(f"  -> Mejor modelo guardado (val acc={val_acc:.4f}  loss={val_loss:.4f})")
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1

        # ── EarlyStopping ──────────────────────────────────────────────────────
        if epochs_no_improve >= patience:
            print(f"\nEarly stopping en epoca {epoch} (sin mejora en {patience} epocas).")
            break

    print(f"\nEntrenamiento completado. Mejor val accuracy: {best_val_acc:.4f}")
    print(f"Modelo guardado en: {output}")
    save_plots(history, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset",  default="/home/dorfin/dataset/face_age")
    parser.add_argument("--epochs",   type=int, default=20)
    parser.add_argument("--output",   default="age_model.pth")
    parser.add_argument("--batch",    type=int, default=32)
    parser.add_argument("--patience", type=int, default=5)
    args = parser.parse_args()

    train(args.dataset, args.epochs, args.output, args.batch, args.patience)
