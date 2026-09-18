param location string
param name string
param tags object
param workspaceResourceId string

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    DisableIpMasking: false
    DisableLocalAuth: true
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: workspaceResourceId
  }
}

output connectionString string = applicationInsights.properties.ConnectionString
output id string = applicationInsights.id