import pandas as pd
import numpy as np
df = pd.DataFrame({'a': [1.0, pd.NA]})
try:
    print(df.values.astype(np.float32))
except Exception as e:
    print("Error 1:", e)
    
try:
    print(df.astype(float).values.astype(np.float32))
except Exception as e:
    print("Error 2:", e)
