import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from torch.optim import Adam
from optuna_db_controller import create_study

# Seeds für Reproduzierbarkeit setzen
np.random.seed(0)
torch.manual_seed(0)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Daten laden
data = pd.read_csv('../data/Crude_Oil_data.csv')
data['date'] = pd.to_datetime(data['date'])
data = data.set_index('date')[['close']]  # Nur "close" behalten

# Skalierung der Daten
def min_max_scaling(data):
    min_vals = data.min()
    max_vals = data.max()
    scaled_data = (data - min_vals) / (max_vals - min_vals)
    return scaled_data, min_vals, max_vals

scaled_data, min_vals, max_vals = min_max_scaling(data)

# Daten für RNN vorbereiten
def prepare_data_for_rnn(data_frame, n_steps):
    output = data_frame.copy()
    n_features = data_frame.shape[1]
    for i in range(1, n_steps + 1):
        output[f'close(t-{i})'] = data_frame['close'].shift(i)  # Nur "close" verwenden
    output.dropna(inplace=True)
    return output

lookback_range = 7
shifted_data = prepare_data_for_rnn(scaled_data, lookback_range)

# Daten in Tensoren umwandeln
def create_tensors(data_frame):
    X = data_frame.drop(['close'], axis=1).values
    y = data_frame['close'].values
    X = torch.tensor(X, dtype=torch.float32).to(device)
    y = torch.tensor(y, dtype=torch.float32).to(device)
    return X, y

X, y = create_tensors(shifted_data)
dataset = TensorDataset(X, y)

# Datensatz in Trainings-, Validierungs- und Testdatensatz aufteilen
train_size = int(0.7 * len(dataset))  # 70% für Training
val_size = int(0.2 * len(dataset))    # 20% für Validierung
test_size = len(dataset) - train_size - val_size  # 10% für Test

train_dataset, val_dataset, test_dataset = torch.utils.data.random_split(dataset, [train_size, val_size, test_size])

# GRU Modell
class GRUModel(nn.Module):
    def __init__(self, input_size, hidden_layer_size, output_size, num_layers):
        super(GRUModel, self).__init__()
        self.hidden_layer_size = hidden_layer_size
        self.num_layers = num_layers
        self.gru = nn.GRU(input_size, hidden_layer_size, num_layers, batch_first=True)
        self.linear = nn.Linear(hidden_layer_size, output_size)

    def forward(self, input_seq):
        gru_out, _ = self.gru(input_seq)
        predictions = self.linear(gru_out[:, -1, :])
        return predictions

# Optuna-Studie erstellen
def objective(trial):
    input_size = 1  # Nur "close" als Feature
    output_size = 1  # Wir sagen die Schlusskurse voraus
    hidden_layer_size = trial.suggest_int('hidden_layer_size', 10, 100)
    num_layers = trial.suggest_int('num_layers', 1, 3)  # Neue Zeile für die Anzahl der Schichten
    batch_size = trial.suggest_int('batch_size', 16, 128)
    learn_rate = trial.suggest_float('learn_rate', 1e-3, 1e-1)
    epochs = trial.suggest_int('epochs', 10, 100)  # Hyperparameter für die Anzahl der Epochen

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    model = GRUModel(input_size, hidden_layer_size, output_size, num_layers).to(device)  # Anpassung des Modells
    criterion = nn.MSELoss()
    optimizer = Adam(model.parameters(), lr=learn_rate)

    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            X_batch = X_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_batch = y_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_pred = model(X_batch)
            loss = criterion(y_pred, y_batch)
            loss.backward()
            optimizer.step()

    model.eval()
    val_losses = []
    with torch.no_grad():
        for X_batch, y_batch in val_loader:
            X_batch = X_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_batch = y_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_pred = model(X_batch)
            loss = criterion(y_pred, y_batch)
            val_losses.append(loss.item())

    return np.mean(val_losses)

# Optuna-Studie starten
study = create_study()
study.optimize(objective, n_trials=10)

# Beste Ergebnisse anzeigen
print('\nBest trial:')
trial = study.best_trial

print('Value: ', trial.value)
print('Params: ')
for key, value in trial.params.items():
    print(f'    {key}: {value}')
print('')

'''# Verwendung der besten Hyperparameter für das endgültige Training und die Bewertung
best_params = trial.params
hidden_layer_size = best_params['hidden_layer_size']
num_layers = best_params['num_layers']  # Hinzufügen der Anzahl der Schichten
batch_size = best_params['batch_size']
learn_rate = best_params['learn_rate']
epochs = best_params['epochs']

input_size = 1
output_size = 1

train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

model = GRUModel(input_size, hidden_layer_size, output_size, num_layers).to(device)
criterion = nn.MSELoss()
optimizer = Adam(model.parameters(), lr=learn_rate)

# Training des Modells mit den besten Hyperparametern
train_losses = []
val_losses = []

for epoch in range(epochs):
    model.train()
    batch_train_losses = []
    for X_batch, y_batch in train_loader:
        optimizer.zero_grad()
        X_batch = X_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
        y_batch = y_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
        y_pred = model(X_batch)
        loss = criterion(y_pred, y_batch)
        loss.backward()
        optimizer.step()
        batch_train_losses.append(loss.item())
    train_losses.append(np.mean(batch_train_losses))

    model.eval()
    batch_val_losses = []
    with torch.no_grad():
        for X_batch, y_batch in val_loader:
            X_batch = X_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_batch = y_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
            y_pred = model(X_batch)
            loss = criterion(y_pred, y_batch)
            batch_val_losses.append(loss.item())
    val_losses.append(np.mean(batch_val_losses))

    print(f'Epoch {epoch + 1}, Train Loss: {train_losses[-1]}, Validation Loss: {val_losses[-1]}')

# Lernkurven visualisieren um Overfitting sichtbarer zu machen
plt.figure(figsize=(10, 6))
plt.plot(train_losses, label='Train Loss')
plt.plot(val_losses, label='Validation Loss')
plt.xlabel('Epochs')
plt.ylabel('Loss')
plt.legend()
plt.title('Train and Validation Loss over Epochs')
plt.show()

# Modell evaluieren
model.eval()
test_losses = []
predictions = []
actuals = []
with torch.no_grad():
    for X_batch, y_batch in test_loader:
        X_batch = X_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
        y_batch = y_batch.unsqueeze(-1)  # Dimension für "close" hinzufügen
        y_pred = model(X_batch)
        loss = criterion(y_pred, y_batch)
        test_losses.append(loss.item())
        predictions.extend(y_pred.cpu().numpy())
        actuals.extend(y_batch.cpu().numpy())

test_loss = np.mean(test_losses)
print(f'Test Loss: {test_loss}')

# Vorhersagen und tatsächliche Werte zurückskalieren
def inverse_scaling(scaled_values, min_val, max_val):
    return scaled_values * (max_val - min_val) + min_val

predictions = inverse_scaling(np.array(predictions).reshape(-1, 1), min_vals['close'], max_vals['close']).flatten()
actuals = inverse_scaling(np.array(actuals).reshape(-1, 1), min_vals['close'], max_vals['close']).flatten()

# Visualisierung der Vorhersagen und der tatsächlichen Werte
plt.figure(figsize=(14, 5))
dates = data.index[lookback_range + train_size:lookback_range + train_size + len(actuals)]
plt.plot(dates, actuals, label='Actual Prices')
plt.plot(dates, predictions, label='Predicted Prices')
plt.title('Crude Oil Prices Prediction on Test Data')
plt.xlabel('Time (Days)')
plt.ylabel('Price (USD)')
plt.legend()
plt.show()
'''
