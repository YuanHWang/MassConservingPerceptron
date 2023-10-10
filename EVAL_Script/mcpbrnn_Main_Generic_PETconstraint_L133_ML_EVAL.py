import argparse
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader, BatchSampler, RandomSampler
from torch import Tensor
from torch.nn.parameter import Parameter
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import torch.utils.data as Data
from torch.autograd import Variable
from typing import Tuple
import numpy as np
import pandas as pd
import os
import math
import datetime
from tqdm import tqdm
import sys
from sklearn.metrics import mean_squared_error
import csv
# import class
from MCPBRNN_lib_tools.NodeZoo_SP import MCPBRNN_Generic_PETconstraint_Multi_parallel_Original, MCPBRNN_PETconstraint_Generic,MCPBRNN_Generic_PETconstraint_Multi_parallel_firstlayer, MCPBRNN_Generic_PETconstraint_Linear_Layer, MCPBRNN_Generic_PETconstraint_Multi_parallel_middlelayer, MCPBRNN_Generic_PETconstraint_Multi_parallel_middlelayer_original,MCPBRNN_PETconstraint_Generic
from MCPBRNN_lib_tools.Eval_Metric import ANLL_out, correlation, NS, KGE
from MCPBRNN_lib_tools.Loss_Function import  KGELoss

parser = argparse.ArgumentParser()

parser.add_argument('--case_no',
                        type=int,
                        default=0,
                        help="Case Number: Initial values for the parameters of Hydro-MC-simple-LSTM")

parser.add_argument('--epoch_no',
                        type=int,
                        default=3000,
                        help="number of epoch to train the network")

parser.add_argument('--depth_size1',
                        type=int,
                        default=1,
                        help="number of hidden nodes")

parser.add_argument('--depth_size2',
                        type=int,
                        default=3,
                        help="number of hidden nodes")

parser.add_argument('--depth_size3',
                        type=int,
                        default=3,
                        help="number of hidden nodes")

parser.add_argument('--time_lag',
                        type=int,
                        default=0,
                        help="number of input time lag for the gate")

parser.add_argument('--gate_dim',
                        type=int,
                        default=1,
                        help="number of nodes for ANN functions")

parser.add_argument('--gate_dim_ucorr',
                        type=int,
                        default=1,
                        help="number of nodes for ANN functions at input gate for correcting precipitation")

parser.add_argument('--seed_no',
                        type=int,
                        default=2925,
                        help="specify torch random seed")

parser.add_argument('--hidden_size_old',
                        type=int,
                        default=1,
                        help="specify the number of mcpbrnn Node")

cfg = vars(parser.parse_args())

# setup random seed
seed_no = cfg["seed_no"]
np.random.seed(seed_no)
torch.manual_seed(seed_no)

# Define timesteps
lag = 0
time_lag = cfg["time_lag"]
spinLen = 1095 - time_lag - lag
traintimeLen = 8400 - time_lag - lag
timeLen = 15705 - lag 
timeLenR = 15705 - lag - spinLen

# Define Matrix size & Hyperparameters
input_size = 1
hidden_sizeM = 1
hidden_size = cfg["hidden_size_old"]
depth_size1 = cfg["depth_size1"]
depth_size2 = cfg["depth_size2"]
depth_size3 = cfg["depth_size3"]
gate_dim = cfg["gate_dim"]
gate_dim_ucorr = cfg["gate_dim_ucorr"]
num_features = 1
seq_length = 1
input_size_dyn = 1
input_size_stat = 0
num_output = 1
num_epochs = cfg["epoch_no"]
batch_size = timeLen #len_train+len_valid+len_test-seq_length+1
learning_rate = 0.025
learning_rates = {300: 0.0125, 600: 0.0125}
hidden_sizeMo = depth_size1

# Define case & directory
CaseName = 'ML_DNN_MCPBRNN_Generic_Layer-' + str(depth_size1) + '-' + str(depth_size2) + '-' + str(depth_size3) + '_case_' + str(cfg["case_no"]) 
directory = CaseName
#parent_dir = "/home/u9/yhwang0730/PB-LSTM-Papers/20230412-Single-Node-Cases"
parent_dir = "/Users/yhwang/Desktop/HPC_DownloadTemp/2023-Spring-New/20230412-Single-Node-Cases"
# Best Case for generic model 

if depth_size1==1 and depth_size2==3 and depth_size3==3:
   Ini_dir ="results_multinode/ML-Layer-1-3-3/ML_DNN_MCPBRNN_Generic_Layer-1-3-3_case_10/model_epoch500.pt"

path = os.path.join(parent_dir, directory)
isExist = os.path.exists(path)
if not isExist:
  os.mkdir(path)
  print("The new directory is created!")
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

## Import Data
F_data = pd.read_csv('../20220527-MDUPLEX-LeafRiver/LeafRiverDaily_43YR.txt', header=None, delimiter=r"\s+")
F_data = F_data.rename(columns={0: 'P', 1: 'PET', 2: 'Q'})

# Skill Flag Training
SkillFlag = pd.read_csv('../20220527-MDUPLEX-LeafRiver/LeafRiverDaily_43YR_Flag.txt', header=None, delimiter=r"\s+")
SkillFlag = SkillFlag.rename(columns={0: 'Flag'})
SF = torch.tensor(SkillFlag['Flag'])
Mask_Test = SF.eq(1).unsqueeze(1)
Mask_Select = SF.eq(0).unsqueeze(1)
Mask_Train = SF.eq(-1).unsqueeze(1)
Mask_Spin = SF.eq(-99999).unsqueeze(1)

Xmean1=0.0
Xmean2=0.0
Xmean3=0.0
Xstd1=1.0
Xstd2=1.0
Xstd3=1.0
#print(F2_data['Qsim'])
F_data['P'][:] = (F_data['P'][:]-Xmean1)/Xstd1
F_data['Q'][:] = (F_data['Q'][:]-Xmean2)/Xstd2
F_data['PET'][:] = (F_data['PET'][:]-Xmean3)/Xstd3

# Define output matrix
par_no = 0 # Temporarily not save the parameter value
skillmetric = 7
OutMatrix = np.zeros((num_epochs,par_no+skillmetric*4+3))

# Define output index
Out_hidden = np.zeros((timeLen,1))
#Out_cell = np.zeros((timeLen,num_epochs))
#Out_loss = np.zeros((timeLen,num_epochs))
#Out_bypass = np.zeros((timeLen,num_epochs))
#Out_i_gate = np.zeros((timeLen,num_epochs))
#Out_o_gate = np.zeros((timeLen,num_epochs))
#Out_l_gate = np.zeros((timeLen,num_epochs))
#Out_lc_gate = np.zeros((timeLen,num_epochs))
#Out_f_gate = np.zeros((timeLen,num_epochs))
#Teaching_Flag = np.zeros((timeLen,num_epochs))

x_data1 = np.array(F_data['P']).reshape(timeLen,-1)
x_data2 = np.array(F_data['PET']).reshape(timeLen,-1)
x_data = np.concatenate((x_data1, x_data2), axis=1)
y_data = np.array(F_data['Q']).reshape(timeLen,-1)

train_x = x_data[0:timeLen,:]
train_y = y_data[0:timeLen,:]

num_samples, num_features = train_x.shape
x_new = np.zeros((num_samples - seq_length + 1, seq_length, num_features))
y_new = np.zeros((num_samples - seq_length + 1, 1))

for i in range(0, x_new.shape[0]):
    x_new[i, :, :num_features] = train_x[i:i + seq_length, :]
    y_new[i, :] = train_y[i + seq_length - 1, 0]
       
x_new = torch.tensor(x_new)
y_new = torch.tensor(y_new)
x_new = x_new.float()
y_new = y_new.float()
trainx, trainy = Variable(x_new), Variable(y_new)

class Model(nn.Module):
    """Wrapper class that connects LSTM/EA-LSTM with fully connceted layer"""

    def __init__(self,
                 input_size_dyn: int,
                 input_size_stat: int,
                 hidden_size1: int,
                 hidden_size2: int,
                 hidden_size3: int,                 
                 spinLen: int,
                 traintimeLen: int,
                 initial_forget_bias: int = 0,
                 dropout: float = 0.0):
        """Initialize model.
        Parameters
        ----------
        input_size_dyn: int
            Number of dynamic input features.
        input_size_stat: int
            Number of static input features (used in the EA-LSTM input gate).
        hidden_size: int
            Number of LSTM cells/hidden units.
        initial_forget_bias: int
            Value of the initial forget gate bias. (default: 5)
        dropout: float
            Dropout probability in range(0,1). (default: 0.0)
        concat_static: bool
            If True, uses standard LSTM otherwise uses EA-LSTM
        no_static: bool
            If True, runs standard LSTM
        """
        super(Model, self).__init__()
        self.input_size_dyn = input_size_dyn
        self.input_size_stat = input_size_stat
        self.hidden_size1 = depth_size1
        self.hidden_size2 = depth_size2  
        self.hidden_size3 = depth_size3                
        self.spinLen = spinLen
        self.traintimeLen = traintimeLen        
        self.initial_forget_bias = initial_forget_bias
        self.dropout_rate = dropout       
        self.batch_size = batch_size 

        self.MCPBRNNNode_Layer1 = MCPBRNN_PETconstraint_Generic(input_size=input_size_dyn,
                         hidden_size=depth_size1,
                         gate_dim=gate_dim,
                         gate_dim_ucorr=gate_dim_ucorr,  
                         spinLen=spinLen,
                         traintimeLen=traintimeLen,              
                         initial_forget_bias=initial_forget_bias)

        self.dropout = nn.Dropout(p=dropout)

        self.MCPBRNNNode_Layer12_linear = MCPBRNN_Generic_PETconstraint_Linear_Layer(input_size=input_size_dyn,
                         hidden_size_old=depth_size1,
                         hidden_size_new=depth_size2)

        self.MCPBRNNNode_Layer2 = MCPBRNN_Generic_PETconstraint_Multi_parallel_middlelayer(input_size=input_size_dyn,
                         hidden_size=depth_size2,
                         gate_dim=gate_dim,
                         gate_dim_ucorr=gate_dim_ucorr,
                         spinLen=spinLen,
                         traintimeLen=traintimeLen,
                         initial_forget_bias=initial_forget_bias)

        self.MCPBRNNNode_Layer23_linear = MCPBRNN_Generic_PETconstraint_Linear_Layer(input_size=input_size_dyn,
                         hidden_size_old=depth_size2,
                         hidden_size_new=depth_size3)

        self.MCPBRNNNode_Layer3 = MCPBRNN_Generic_PETconstraint_Multi_parallel_middlelayer(input_size=input_size_dyn,
                         hidden_size=depth_size3,
                         gate_dim=gate_dim,
                         gate_dim_ucorr=gate_dim_ucorr,
                         spinLen=spinLen,
                         traintimeLen=traintimeLen,
                         initial_forget_bias=initial_forget_bias)

        self.MCPBRNNNode_Layer3out_linear = MCPBRNN_Generic_PETconstraint_Linear_Layer(input_size=input_size_dyn,
                         hidden_size_old=depth_size3,
                         hidden_size_new=1)

    def forward(self, x_d, epoch, time_lag, y_eval):
        """Run forward pass through the model.
        Parameters
        ----------
        x_d : torch.Tensor
            Tensor containing the dynamic input features of shape [batch, seq_length, n_features]
        Returns
        -------
        out : torch.Tensor
            Tensor containing the network predictions
        h_n : torch.Tensor
            Tensor containing the hidden states of each time step
        c_n : torch,Tensor
            Tensor containing the cell states of each time step
        """
        h_t, c_t, l_t, lc_t, bp_t, i, oo, ol, ol_constraint, f, obs_std = self.MCPBRNNNode_Layer1(x_d, epoch, time_lag, y_eval)   

        h_t_layer2_in = self.MCPBRNNNode_Layer12_linear(h_t)
        x_layer2 = torch.cat((h_t_layer2_in, x_d[:,:,1]), 1)
        x_d_layer2 = x_layer2.unsqueeze(1)

        h_t_layer2, c_t_layer2, l_t_layer2, lc_t_layer2, bp_t_layer2, i_layer2, oo_layer2, ol_layer2, ol_constraint_layer2, f_layer2, obs_std_layer2 = self.MCPBRNNNode_Layer2(x_d_layer2, epoch, time_lag, y_eval)
        h_t_layer2_out = self.MCPBRNNNode_Layer23_linear(h_t_layer2)

        x_layer3 = torch.cat((h_t_layer2_out, x_d[:,:,1]), 1)
        x_d_layer3 = x_layer3.unsqueeze(1)

        h_t_layer3_out, c_t_layer3, l_t_layer3, lc_t_layer3, bp_t_layer3, i_layer3, oo_layer3, ol_layer3, ol_constraint_layer3, f_layer3, obs_std_layer3  = self.MCPBRNNNode_Layer3(x_d_layer3, epoch, time_lag, y_eval)
        h_t_layer3 = self.MCPBRNNNode_Layer3out_linear(h_t_layer3_out)

        last_h = self.dropout(h_t_layer3)      
        out = last_h        

        return out, h_t, h_t_layer2, h_t_layer3, c_t, c_t_layer2, c_t_layer3, l_t, l_t_layer2, l_t_layer3, bp_t, bp_t_layer2, bp_t_layer3, i, i_layer2, i_layer3, oo, oo_layer2, oo_layer3, ol, ol_layer2, ol_layer3, ol_constraint, ol_constraint_layer2, ol_constraint_layer3, f, f_layer2, f_layer3, obs_std, obs_std_layer2, obs_std_layer3

model = Model(input_size_dyn=input_size_dyn,
                input_size_stat=input_size_stat,
                hidden_size1=depth_size1,
                hidden_size2=depth_size2,     
                hidden_size3=depth_size3,                                
                spinLen=spinLen,
                traintimeLen=traintimeLen,              
                initial_forget_bias=0,
                dropout=0).to(device)

weight_IC_file = Ini_dir
model.load_state_dict(torch.load(weight_IC_file))

loss_func = KGELoss()

train_dataset = Data.TensorDataset(trainx, trainy)
loader = Data.DataLoader(
         dataset=train_dataset, 
         batch_size=batch_size, 
         shuffle=False, num_workers=0)

optimizer = torch.optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=learning_rate)

for name, param in model.state_dict().items():
    print(name)
    print(param)

savetext = CaseName + '/' +'model_epoch0.pt'
torch.save(model.state_dict(), savetext)

model.train()
for epoch in range(1,1+1): 

    if epoch in learning_rates.keys():
        for param_group in optimizer.param_groups:
            param_group["lr"] = learning_rates[epoch]

    pbar = tqdm(loader, file=sys.stdout)  
    pbar.set_description(f'# Epoch {epoch}') 

    for data in pbar:
        optimizer.zero_grad()
        x, y,= data
        predictions = model(x,epoch, time_lag, y)[0]  
        #predictions = model(x,epoch, time_lag, y)[1]      
        sim = torch.masked_select(predictions, Mask_Train).unsqueeze(1)       
        obs =  torch.masked_select(y, Mask_Train).unsqueeze(1)
        loss = loss_func(sim, obs)        
        #loss.backward()
        #optimizer.step()
        predictions = model(x,epoch, time_lag, y)[0]
        sim = torch.masked_select(predictions, Mask_Train).unsqueeze(1)
        obs =  torch.masked_select(y, Mask_Train).unsqueeze(1)
        sim_select = torch.masked_select(predictions, Mask_Select).unsqueeze(1)
        obs_select =  torch.masked_select(y, Mask_Select).unsqueeze(1)
        sim_test = torch.masked_select(predictions, Mask_Test).unsqueeze(1)
        obs_test =  torch.masked_select(y, Mask_Test).unsqueeze(1)
        sim_spinup = torch.masked_select(predictions, Mask_Spin).unsqueeze(1)
        obs_spinup =  torch.masked_select(y, Mask_Spin).unsqueeze(1)

    for name, param in model.state_dict().items():
        print(name)
        print(param)

    Result = model(x,epoch, time_lag, y)
    out_eval = Result[0]
    hidden_eval = Result[1]    
    cell_eval = Result[4]
    loss_eval = Result[7]
    bypass_eval = Result[10]
    i_gate = Result[13]
    o_gate = Result[16]
    l_gate = Result[19]
    lc_gate = Result[22]    
    f_gate = Result[25]
    hidden_eval_layer2 = Result[2]    
    cell_eval_layer2 = Result[5]
    loss_eval_layer2 = Result[8]
    bypass_eval_layer2 = Result[11]
    i_gate_layer2 = Result[14]
    o_gate_layer2 = Result[17]
    l_gate_layer2 = Result[20]
    lc_gate_layer2 = Result[23]    
    f_gate_layer2 = Result[26]
    hidden_eval_layer3 = Result[3]    
    cell_eval_layer3 = Result[6]
    loss_eval_layer3 = Result[9]
    bypass_eval_layer3 = Result[12]
    i_gate_layer3 = Result[15]
    o_gate_layer3 = Result[18]
    l_gate_layer3 = Result[21]
    lc_gate_layer3 = Result[24]    
    f_gate_layer3 = Result[27]

    yout_eval = y.detach().cpu().numpy()    
    pout_eval = predictions.detach().cpu().numpy()   
    out_eval = out_eval.detach().cpu().numpy()       
    hidden_eval = hidden_eval.detach().cpu().numpy()       
    cell_eval = cell_eval.detach().cpu().numpy()
    loss_eval = loss_eval.detach().cpu().numpy() 
    bypass_eval = bypass_eval.detach().cpu().numpy()    
    i_gate = i_gate.detach().cpu().numpy()
    o_gate = o_gate.detach().cpu().numpy()
    l_gate = l_gate.detach().cpu().numpy()
    lc_gate = lc_gate.detach().cpu().numpy()    
    f_gate = f_gate.detach().cpu().numpy()      

    hidden_eval_layer2 = hidden_eval_layer2.detach().cpu().numpy()       
    cell_eval_layer2 = cell_eval_layer2.detach().cpu().numpy()
    loss_eval_layer2 = loss_eval_layer2.detach().cpu().numpy() 
    bypass_eval_layer2 = bypass_eval_layer2.detach().cpu().numpy()    
    i_gate_layer2 = i_gate_layer2.detach().cpu().numpy()
    o_gate_layer2 = o_gate_layer2.detach().cpu().numpy()
    l_gate_layer2 = l_gate_layer2.detach().cpu().numpy()
    lc_gate_layer2 = lc_gate_layer2.detach().cpu().numpy()    
    f_gate_layer2 = f_gate_layer2.detach().cpu().numpy()  

    hidden_eval_layer3 = hidden_eval_layer3.detach().cpu().numpy()       
    cell_eval_layer3 = cell_eval_layer3.detach().cpu().numpy()
    loss_eval_layer3 = loss_eval_layer3.detach().cpu().numpy() 
    bypass_eval_layer3 = bypass_eval_layer3.detach().cpu().numpy()    
    i_gate_layer3 = i_gate_layer3.detach().cpu().numpy()
    o_gate_layer3 = o_gate_layer3.detach().cpu().numpy()
    l_gate_layer3 = l_gate_layer3.detach().cpu().numpy()
    lc_gate_layer3 = lc_gate_layer3.detach().cpu().numpy()    
    f_gate_layer3 = f_gate_layer3.detach().cpu().numpy() 

    #calculate the skill
    sim = sim.detach().cpu().numpy()  
    obs = obs.detach().cpu().numpy()  
    sim_spinup = sim_spinup.detach().cpu().numpy()   
    obs_spinup = obs_spinup.detach().cpu().numpy()  
    sim_select = sim_select.detach().cpu().numpy()   
    obs_select = obs_select.detach().cpu().numpy()  
    sim_test = sim_test.detach().cpu().numpy()        
    obs_test = obs_test.detach().cpu().numpy()  

    pout_eval[pout_eval < 0] = 0
    out_eval[out_eval < 0] = 0

    [B, E, C, D, G] =KGE(sim, obs)
    A = NS(sim, obs)
    F = mean_squared_error(obs, sim)

    sz = obs.shape[0]
    [KGEtimelag_1, X1, X2, X3, X4] =KGE(sim[0+1:sz], obs[0:sz-1])   
    [KGEtimelag_2, X1, X2, X3, X4] =KGE(sim[0+2:sz], obs[0:sz-2])   
    [KGEtimelag_3, X1, X2, X3, X4] =KGE(sim[0+3:sz], obs[0:sz-3])   
    OutMatrix[epoch-1,par_no+28] = KGEtimelag_1
    OutMatrix[epoch-1,par_no+29] = KGEtimelag_2
    OutMatrix[epoch-1,par_no+30] = KGEtimelag_3

    [B2, E2, C2, D2, G2] =KGE(sim_select, obs_select)
    A2 = NS(sim_select, obs_select)
    F2 = mean_squared_error(obs_select, sim_select)

    [B3, E3, C3, D3, G3] =KGE(sim_test, obs_test)
    A3 = NS(sim_test, obs_test)
    F3 = mean_squared_error(obs_test, sim_test)    

    [B4, E4, C4, D4, G4] =KGE(sim_spinup, obs_spinup)
    A4 = NS(sim_spinup, obs_spinup)
    F4 = mean_squared_error(obs_spinup, sim_spinup)

    OutMatrix[epoch-1,par_no] = A
    OutMatrix[epoch-1,par_no+7] = A2    
    OutMatrix[epoch-1,par_no+14] = A3 
    OutMatrix[epoch-1,par_no+21] = A4 

    if np.isnan(B):
       OutMatrix[epoch-1,par_no+1] = -99999
    else:
       OutMatrix[epoch-1,par_no+1] = B

    if np.isnan(B2):
       OutMatrix[epoch-1,par_no+8] = -99999
    else:
       OutMatrix[epoch-1,par_no+8] = B2

    if np.isnan(B3):
       OutMatrix[epoch-1,par_no+15] = -99999
    else:
       OutMatrix[epoch-1,par_no+15] = B3

    if np.isnan(B4):
       OutMatrix[epoch-1,par_no+22] = -99999
    else:
       OutMatrix[epoch-1,par_no+22] = B4

    OutMatrix[epoch-1,par_no+2] = C
    OutMatrix[epoch-1,par_no+3] = D 
    OutMatrix[epoch-1,par_no+9] = C2
    OutMatrix[epoch-1,par_no+10] = D2     
    OutMatrix[epoch-1,par_no+16] = C3
    OutMatrix[epoch-1,par_no+17] = D3 
    OutMatrix[epoch-1,par_no+23] = C4
    OutMatrix[epoch-1,par_no+24] = D4 

    if np.isnan(E):  
       OutMatrix[epoch-1,par_no+4] = -99999
    else:  
       OutMatrix[epoch-1,par_no+4] = E

    if np.isnan(E2):
       OutMatrix[epoch-1,par_no+11] = -99999
    else:  
       OutMatrix[epoch-1,par_no+11] = E2       

    if np.isnan(E3):
       OutMatrix[epoch-1,par_no+18] = -99999
    else:  
       OutMatrix[epoch-1,par_no+18] = E3 

    if np.isnan(E4):
       OutMatrix[epoch-1,par_no+25] = -99999
    else:  
       OutMatrix[epoch-1,par_no+25] = E4

    OutMatrix[epoch-1,par_no+5] = F
    OutMatrix[epoch-1,par_no+12] = F2 
    OutMatrix[epoch-1,par_no+19] = F3 
    OutMatrix[epoch-1,par_no+26] = F4 

    if np.isnan(G):  
       OutMatrix[epoch-1,par_no+6] = -99999
    else:  
       OutMatrix[epoch-1,par_no+6] = G

    if np.isnan(G2):
       OutMatrix[epoch-1,par_no+13] = -99999
    else:  
       OutMatrix[epoch-1,par_no+13] = G2       

    if np.isnan(G3):
       OutMatrix[epoch-1,par_no+20] = -99999
    else:  
       OutMatrix[epoch-1,par_no+20] = G3 

    if np.isnan(G4):
       OutMatrix[epoch-1,par_no+27] = -99999
    else:  
       OutMatrix[epoch-1,par_no+27] = G4

    #OutMatrix[epoch-1,0]= model.state_dict()["MCPBRNNNode.weight_r_yom"][:]
    #OutMatrix[epoch-1,1]= model.state_dict()["MCPBRNNNode.weight_r_ylm"][:]
    #OutMatrix[epoch-1,2]= model.state_dict()["MCPBRNNNode.weight_r_yfm"][:]
    #OutMatrix[epoch-1,3]= model.state_dict()["MCPBRNNNode.weight_r_yvm"][:]    
    #OutMatrix[epoch-1,3]= model.state_dict()["MCPBRNNNode.bias_b0_yom"][:]
    #OutMatrix[epoch-1,4]= model.state_dict()["MCPBRNNNode.weight_b1_yom"][:]
    #OutMatrix[epoch-1,5]= model.state_dict()["MCPBRNNNode.bias_b0_ylm"][:]
    #OutMatrix[epoch-1,6]= model.state_dict()["MCPBRNNNode.weight_b2_ylm"][:]
    #OutMatrix[epoch-1,8]= model.state_dict()["MCPBRNNNode.weight_s_yvm"][:]

# Output time series
    Out_hidden[0:timeLen,epoch-1] = out_eval[:,0]       
#    Out_cell[0:timeLen,epoch-1] = cell_eval[:,0]
#    Out_loss[0:timeLen,epoch-1] = loss_eval[:,0]
    #Out_bypass[0:timeLen,epoch-1] = bypass_eval[:,0]
    #Out_i_gate [0:timeLen,epoch-1] = i_gate[:,0]
#    Out_o_gate [0:timeLen,epoch-1] = o_gate[:,0]
#    Out_l_gate [0:timeLen,epoch-1] = l_gate[:,0]    
#    Out_lc_gate [0:timeLen,epoch-1] = lc_gate[:,0]    
#    Out_f_gate [0:timeLen,epoch-1] = f_gate[:,0]

    print(B2)
    
CaseName = "results_multinode/ML-Layer-1-3-3"

# Save timeseries
Out_file = pd.DataFrame(Out_hidden)
outname = CaseName + '/' + 'Outhidden_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)
'''
Out_file = pd.DataFrame(Out_cell)
outname = CaseName + '/' + 'Outcell_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)

Out_file = pd.DataFrame(Out_loss)
outname = CaseName + '/' + 'Outloss_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)

#Out_file = pd.DataFrame(Out_bypass)
#outname = CaseName + '/' + 'Outbypass_' + str(cfg["case_no"]) + '_summary.csv'
#Out_file.to_csv(outname)

#Out_file = pd.DataFrame(Out_i_gate)
#outname = CaseName + '/' + 'Out_gatei_' + str(cfg["case_no"]) + '_summary.csv'
#Out_file.to_csv(outname)

Out_file = pd.DataFrame(Out_o_gate)
outname = CaseName + '/' + 'Out_gateo_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)

Out_file = pd.DataFrame(Out_l_gate)
outname = CaseName + '/' + 'Out_gatel_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)

Out_file = pd.DataFrame(Out_lc_gate)
outname = CaseName + '/' + 'Out_gatelc_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)

Out_file = pd.DataFrame(Out_f_gate)
outname = CaseName + '/' + 'Out_gatef_' + str(cfg["case_no"]) + '_summary.csv'
Out_file.to_csv(outname)'''